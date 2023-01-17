from __future__ import absolute_import, division, print_function
import numpy as np
from radiotools import helper as hp
from radiotools import coordinatesystems as cstrans
from NuRadioMC.SignalGen import askaryan
from NuRadioReco.utilities import units
from NuRadioMC.utilities import medium
from NuRadioReco.utilities import fft
from NuRadioMC.utilities.earth_attenuation import get_weight
from NuRadioMC.SignalProp import propagation
import h5py
import time
import six
import copy
import json
from scipy import constants
# import detector simulation modules
import NuRadioReco.detector.detector as detector
import NuRadioReco.detector.generic_detector as gdetector
import NuRadioReco.framework.sim_station
import NuRadioReco.framework.electric_field
import NuRadioReco.framework.particle
import NuRadioReco.framework.event
from NuRadioReco.detector import antennapattern
from NuRadioReco.utilities import geometryUtilities as geo_utl
from NuRadioReco.framework.parameters import channelParameters as chp
from NuRadioReco.framework.parameters import electricFieldParameters as efp
from NuRadioReco.framework.parameters import showerParameters as shp
# parameters describing simulated Monte Carlo particles
from NuRadioReco.framework.parameters import particleParameters as simp
# parameters set in the event generator
from NuRadioReco.framework.parameters import generatorAttributes as genattrs
import datetime
import logging
from six import iteritems
import yaml
import os
import collections
from NuRadioMC.utilities.Veff import remove_duplicate_triggers
import NuRadioMC.simulation.simulation_base
import NuRadioMC.simulation.simulation_detector
import NuRadioMC.simulation.simulation_emission
import NuRadioMC.simulation.simulation_input_output
import NuRadioMC.simulation.simulation_propagation

STATUS = 31

# logging.basicConfig(format='%(asctime)s %(levelname)s:%(name)s:%(message)s')



logging.setLoggerClass(NuRadioMC.simulation.simulation_base.NuRadioMCLogger)
logging.addLevelName(STATUS, 'STATUS')
logger = logging.getLogger("NuRadioMC")
assert isinstance(logger, NuRadioMC.simulation.simulation_base.NuRadioMCLogger)
# formatter = logging.Formatter('%(asctime)s %(levelname)s:%(name)s:%(message)s')
# ch = logging.StreamHandler()
# ch.setFormatter(formatter)
# logger.addHandler(ch)


class simulation(
    NuRadioMC.simulation.simulation_propagation.simulation_propagation,
    NuRadioMC.simulation.simulation_emission.simulation_emission,
    NuRadioMC.simulation.simulation_detector.simulation_detector,
    NuRadioMC.simulation.simulation_input_output.simulation_input_output
):



    def run(self):
        """
        run the NuRadioMC simulation
        """
        if len(self._fin['xx']) == 0:
            logger.status(f"writing empty hdf5 output file")
            self._write_output_file(empty=True)
            logger.status(f"terminating simulation")
            return 0
        logger.status(f"Starting NuRadioMC simulation")
        t_start = time.time()
        t_last_update = t_start

        unique_event_group_ids = np.unique(self._fin['event_group_ids'])
        self._n_showers = len(self._fin['event_group_ids'])
        self._shower_ids = np.array(self._fin['shower_ids'])
        self._shower_index_array = {}  # this array allows to convert the shower id to an index that starts from 0 to be used to access the arrays in the hdf5 file.

        self._raytracer = self._prop(
            self._ice, self._cfg['propagation']['attenuation_model'],
            log_level=self._log_level_ray_propagation,
            n_frequencies_integration=int(self._cfg['propagation']['n_freq']),
            n_reflections=self._n_reflections,
            config=self._cfg,
            detector=self._det
        )
        for shower_index, shower_id in enumerate(self._shower_ids):
            self._shower_index_array[shower_id] = shower_index

        self._create_meta_output_datastructures()

        # check if the same detector was simulated before (then we can save the ray tracing part)
        pre_simulated = self._check_if_was_pre_simulated()

        # Check if vertex_times exists:
        self._check_vertex_times()

        self._input_time = 0.0
        self._askaryan_time = 0.0
        self._rayTracingTime = 0.0
        self._detSimTime = 0.0
        self._outputTime = 0.0
        self._weightTime = 0.0
        self._distance_cut_time = 0.0

        n_shower_station = len(self._station_ids) * self._n_showers
        iCounter = 0

        # calculate bary centers of station
        self._station_barycenter = self._calculate_station_barycenter()

        # loop over event groups
        for i_event_group_id, event_group_id in enumerate(unique_event_group_ids):
            logger.debug(f"simulating event group id {event_group_id}")
            if self._event_group_list is not None and event_group_id not in self._event_group_list:
                logger.debug(f"skipping event group {event_group_id} because it is not in the event group list provided to the __init__ function")
                continue
            event_indices = np.atleast_1d(np.squeeze(np.argwhere(self._fin['event_group_ids'] == event_group_id)))

            # the weight calculation is independent of the station, so we do this calculation only once
            # the weight also depends just on the "mother" particle, i.e. the incident neutrino which determines
            # the propability of arriving at our simulation volume. All subsequent showers have the same weight. So
            # we calculate it just once and save it to all subshowers.
            t1 = time.time()

            self._primary_index = event_indices[0]
            # determine if a particle (neutrinos, or a secondary interaction of a neutrino, or surfaec muons) is simulated
            particle_mode = "simulation_mode" not in self._fin_attrs or self._fin_attrs['simulation_mode'] != "emitter"
            self._mout['weights'][event_indices] = np.ones(len(event_indices))  # for a pulser simulation, every event has the same weight
            if particle_mode:
                self._calculate_particle_weights(event_indices)

            self._weightTime += time.time() - t1
            # skip all events where neutrino weights is zero, i.e., do not
            # simulate neutrino that propagate through the Earth
            if self._mout['weights'][self._primary_index] < self._cfg['speedup']['minimum_weight_cut']:
                logger.debug("neutrino weight is smaller than {}, skipping event".format(self._cfg['speedup']['minimum_weight_cut']))
                continue

            # these quantities get computed to apply the distance cut as a function of shower energies
            # the shower energies of closeby showers will be added as they can constructively interfere
            if self._cfg['speedup']['distance_cut']:
                t_tmp = time.time()
                shower_energies = np.array(self._fin['shower_energies'])[event_indices]
                vertex_positions = np.array([np.array(self._fin['xx'])[event_indices],
                                             np.array(self._fin['yy'])[event_indices],
                                             np.array(self._fin['zz'])[event_indices]]).T
                vertex_distances = np.linalg.norm(vertex_positions - vertex_positions[0], axis=1)
                self._distance_cut_time += time.time() - t_tmp

            triggered_showers = {}  # this variable tracks which showers triggered a particular station

            # loop over all stations (each station is treated independently)
            for iSt, self._station_id in enumerate(self._station_ids):
                t1 = time.time()
                triggered_showers[self._station_id] = []
                logger.debug(f"simulating station {self._station_id}")

                if self._cfg['speedup']['distance_cut']:
                    # perform a quick cut to reject event group completely if no shower is close enough to the station
                    t_tmp = time.time()
                    vertex_distances_to_station = np.linalg.norm(vertex_positions - self._station_barycenter[iSt], axis=1)
                    distance_cut = self._get_distance_cut(np.sum(shower_energies)) + 100 * units.m  # 100m safety margin is added to account for extent of station around bary center.
                    if vertex_distances_to_station.min() > distance_cut:
                        logger.debug(f"skipping station {self._station_id} because minimal distance {vertex_distances_to_station.min()/units.km:.1f}km > {distance_cut/units.km:.1f}km (shower energy = {shower_energies.max():.2g}eV) bary center of station {self._station_barycenter[iSt]}")
                        self._distance_cut_time += time.time() - t_tmp
                        iCounter += len(shower_energies)
                        continue
                    self._distance_cut_time += time.time() - t_tmp

                candidate_station = False
                self._sampling_rate_detector = self._det.get_sampling_frequency(self._station_id, 0)
#                 logger.warning('internal sampling rate is {:.3g}GHz, final detector sampling rate is {:.3g}GHz'.format(self.get_sampling_rate(), self._sampling_rate_detector))
                self._n_samples = self._det.get_number_of_samples(self._station_id, 0) / self._sampling_rate_detector / self._dt
                self._n_samples = int(np.ceil(self._n_samples / 2.) * 2)  # round to nearest even integer
                self._ff = np.fft.rfftfreq(self._n_samples, self._dt)
                self._tt = np.arange(0, self._n_samples * self._dt, self._dt)

                ray_tracing_performed = False
                if 'station_{:d}'.format(self._station_id) in self._fin_stations:
                    ray_tracing_performed = (self._raytracer.get_output_parameters()[0]['name'] in self._fin_stations['station_{:d}'.format(self._station_id)]) and self._was_pre_simulated
                self._evt_tmp = NuRadioReco.framework.event.Event(0, 0)

                if particle_mode:
                    # add the primary particle to the temporary event
                    self._evt_tmp.add_particle(self.primary)

                self._create_sim_station()
                # loop over all showers in event group
                # create output data structure for this channel
                sg = self._create_station_output_structure(len(event_indices), self._det.get_number_of_channels(self._station_id))
                for iSh, self._shower_index in enumerate(event_indices):
                    sg['shower_id'][iSh] = self._shower_ids[self._shower_index]
                    iCounter += 1
#                     if(iCounter % max(1, int(n_shower_station / 100.)) == 0):
                    if (time.time() - t_last_update) > 60 :
                        t_last_update = time.time()
                        eta = NuRadioMC.simulation.simulation_base.pretty_time_delta((time.time() - t_start) * (n_shower_station - iCounter) / iCounter)
                        total_time_sum = self._input_time + self._rayTracingTime + self._detSimTime + self._outputTime + self._weightTime + self._distance_cut_time  # askaryan time is part of the ray tracing time, so it is not counted here.
                        total_time = time.time() - t_start
                        tmp_att = 0
                        if total_time > 0:
                            logger.status(
                                "processing event group {}/{} and shower {}/{} ({} showers triggered) = {:.1f}%, ETA {}, time consumption: ray tracing = {:.0f}%, askaryan = {:.0f}%, detector simulation = {:.0f}% reading input = {:.0f}%, calculating weights = {:.0f}%, distance cut {:.0f}%, unaccounted = {:.0f}% ".format(
                                    i_event_group_id,
                                    len(unique_event_group_ids),
                                    iCounter,
                                    n_shower_station,
                                    np.sum(self._mout['triggered']),
                                    100. * iCounter / n_shower_station,
                                    eta,
                                    100. * (self._rayTracingTime - self._askaryan_time) / total_time,
                                    100. * self._askaryan_time / total_time,
                                    100. * self._detSimTime / total_time,
                                    100. * self._input_time / total_time,
                                    100. * self._weightTime / total_time,
                                    100 * self._distance_cut_time / total_time,
                                    100 * (total_time - total_time_sum) / total_time))

                    self._read_input_shower_properties()
                    if particle_mode:
                        logger.debug(f"simulating shower {self._shower_index}: {self._fin['shower_type'][self._shower_index]} with E = {self._fin['shower_energies'][self._shower_index]/units.eV:.2g}eV")
                    x1 = self._shower_vertex  # the interaction point

                    if self._cfg['speedup']['distance_cut']:
                        t_tmp = time.time()
                        # calculate the sum of shower energies for all showers within self._cfg['speedup']['distance_cut_sum_length']
                        mask_shower_sum = np.abs(vertex_distances - vertex_distances[iSh]) < self._cfg['speedup']['distance_cut_sum_length']
                        shower_energy_sum = np.sum(shower_energies[mask_shower_sum])
                        # quick speedup cut using barycenter of station as position
                        distance_to_station = np.linalg.norm(x1 - self._station_barycenter[iSt])
                        distance_cut = self._get_distance_cut(shower_energy_sum) + 100 * units.m  # 100m safety margin is added to account for extent of station around bary center.
                        logger.debug(f"calculating distance cut. Current event has energy {self._fin['shower_energies'][self._shower_index]:.4g}, it is event number {iSh} and {np.sum(mask_shower_sum)} are within {self._cfg['speedup']['distance_cut_sum_length']/units.m:.1f}m -> {shower_energy_sum:.4g}")
                        if distance_to_station > distance_cut:
                            logger.debug(f"skipping station {self._station_id} because distance {distance_to_station/units.km:.1f}km > {distance_cut/units.km:.1f}km (shower energy = {self._fin['shower_energies'][self._shower_index]:.2g}eV) between vertex {x1} and bary center of station {self._station_barycenter[iSt]}")
                            self._distance_cut_time += time.time() - t_tmp
                            continue
                        self._distance_cut_time += time.time() - t_tmp

                    # skip vertices not in fiducial volume. This is required because 'mother' events are added to the event list
                    # if daugthers (e.g. tau decay) have their vertex in the fiducial volume
                    if not self._is_in_fiducial_volume():
                        logger.debug(f"event is not in fiducial volume, skipping simulation {self._fin['xx'][self._shower_index]}, {self._fin['yy'][self._shower_index]}, {self._fin['zz'][self._shower_index]}")
                        continue

                    # for special cases where only EM or HAD showers are simulated, skip all events that don't fulfill this criterion
                    if self._cfg['signal']['shower_type'] == "em":
                        if self._fin['shower_type'][self._shower_index] != "em":
                            continue
                    if self._cfg['signal']['shower_type'] == "had":
                        if self._fin['shower_type'][self._shower_index] != "had":
                            continue

                    if particle_mode:
                        self._create_sim_shower()  # create sim shower
                        self._evt_tmp.add_sim_shower(self._sim_shower)

                    # generate unique and increasing event id per station
                    self._event_ids_counter[self._station_id] += 1
                    self._event_id = self._event_ids_counter[self._station_id]

                    # be careful, zenith/azimuth angle always refer to where the neutrino came from,
                    # i.e., opposite to the direction of propagation. We need the propagation direction here,
                    # so we multiply the shower axis with '-1'
                    if 'zeniths' in self._fin:
                        self._shower_axis = -1 * hp.spherical_to_cartesian(self._fin['zeniths'][self._shower_index], self._fin['azimuths'][self._shower_index])
                    else:
                        self._shower_axis = np.array([0, 0, 1])

                    # calculate correct Cherenkov angle for ice density at vertex position
                    n_index = self._ice.get_index_of_refraction(x1)
                    cherenkov_angle = np.arccos(1. / n_index)

                    # first step: perform raytracing to see if solution exists
                    t2 = time.time()
#                     self._input_time += (time.time() - t1)

                    for channel_id in range(self._det.get_number_of_channels(self._station_id)):
                        x2 = self._det.get_relative_position(self._station_id, channel_id) + self._det.get_absolute_position(self._station_id)
                        logger.debug(f"simulating channel {channel_id} at {x2}")

                        if self._cfg['speedup']['distance_cut']:
                            t_tmp = time.time()
                            if not self._distance_cut_channel(
                                shower_energy_sum,
                                x1,
                                x2
                            ):
                                continue
                            self._distance_cut_time += time.time() - t_tmp

                        self._raytracer.set_start_and_end_point(x1, x2)
                        self._raytracer.use_optional_function('set_shower_axis', self._shower_axis)
                        if pre_simulated and ray_tracing_performed and not self._cfg['speedup']['redo_raytracing']:  # check if raytracing was already performed
                            if self._cfg['propagation']['module'] == 'radiopropa':
                                logger.error('Presimulation can not be used with the radiopropa ray tracer module')
                                raise Exception('Presimulation can not be used with the radiopropa ray tracer module')
                            sg_pre = self._fin_stations["station_{:d}".format(self._station_id)]
                            ray_tracing_solution = {}
                            for output_parameter in self._raytracer.get_output_parameters():
                                ray_tracing_solution[output_parameter['name']] = sg_pre[output_parameter['name']][self._shower_index, channel_id]
                            self._raytracer.set_solution(ray_tracing_solution)
                        else:
                            self._raytracer.find_solutions()

                        if not self._raytracer.has_solution():
                            logger.debug("event {} and station {}, channel {} does not have any ray tracing solution ({} to {})".format(
                                self._event_group_id, self._station_id, channel_id, x1, x2))
                            continue
                        delta_Cs, viewing_angles = self._calculate_viewing_angles(sg, iSh, channel_id, cherenkov_angle)

                        # discard event if delta_C (angle off cherenkov cone) is too large
                        if min(np.abs(delta_Cs)) > self._cfg['speedup']['delta_C_cut']:
                            logger.debug('delta_C too large, event unlikely to be observed, skipping event')
                            continue

                        is_candidate = self._calculate_polarization_angles(sg, iSh, delta_Cs, viewing_angles, ray_tracing_performed, channel_id, n_index)
                        if is_candidate:
                            candidate_station = True
                        # end of ray tracing solutions loop
                    t3 = time.time()
                    self._rayTracingTime += t3 - t2
                    # end of channels loop
                # end of showers loop
                # now perform first part of detector simulation -> convert each efield to voltage
                # (i.e. apply antenna response) and apply additional simulation of signal chain (such as cable delays,
                # amp response etc.)
                if not candidate_station:
                    logger.debug("electric field amplitude too small in all channels, skipping to next event")
                    continue
                t1 = time.time()
                self._station = NuRadioReco.framework.station.Station(self._station_id)
                self._station.set_sim_station(self._sim_station)

                self._simulate_sim_station_detector_response()

                if self._cfg['speedup']['amp_per_ray_solution']:
                    self._channelSignalReconstructor.run(self._evt, self._station.get_sim_station(), self._det)
                    for channel in self._station.get_sim_station().iter_channels():
                        tmp_index = np.argwhere(event_indices == self._get_shower_index(channel.get_shower_id()))[0]
                        sg['max_amp_shower_and_ray'][tmp_index, channel.get_id(), channel.get_ray_tracing_solution_id()] = channel.get_parameter(chp.maximum_amplitude_envelope)
                        sg['time_shower_and_ray'][tmp_index, channel.get_id(), channel.get_ray_tracing_solution_id()] = channel.get_parameter(chp.signal_time)
                start_times = []
                channel_identifiers = []
                for channel in self._sim_station.iter_channels():
                    channel_identifiers.append(channel.get_unique_identifier())
                    start_times.append(channel.get_trace_start_time())
                start_times = np.array(start_times)
                start_times_sort = np.argsort(start_times)
                delta_start_times = start_times[start_times_sort][1:] - start_times[start_times_sort][:-1]  # this array is sorted in time
                split_event_time_diff = float(self._cfg['split_event_time_diff'])
                iSplit = np.atleast_1d(np.squeeze(np.argwhere(delta_start_times > split_event_time_diff)))
                n_sub_events = len(iSplit) + 1
                if n_sub_events > 1:
                    logger.info(f"splitting event group id {self._event_group_id} into {n_sub_events} sub events")

                tmp_station = copy.deepcopy(self._station)
                event_group_has_triggered = False
                for iEvent in range(n_sub_events):
                    iStart = 0
                    iStop = len(channel_identifiers)
                    if n_sub_events > 1:
                        if iEvent > 0:
                            iStart = iSplit[iEvent - 1] + 1
                    if iEvent < n_sub_events - 1:
                        iStop = iSplit[iEvent] + 1
                    indices = start_times_sort[iStart: iStop]
                    if n_sub_events > 1:
                        tmp = ""
                        for start_time in start_times[indices]:
                            tmp += f"{start_time/units.ns:.0f}, "
                        tmp = tmp[:-2] + " ns"
                        logger.info(f"creating event {iEvent} of event group {self._event_group_id} ranging rom {iStart} to {iStop} with indices {indices} corresponding to signal times of {tmp}")
                    self._evt = NuRadioReco.framework.event.Event(self._event_group_id, iEvent)  # create new event

                    if particle_mode:
                        # add MC particles that belong to this (sub) event to event structure
                        # add only primary for now, since full interaction chain is not typically in the input hdf5s
                        self._evt.add_particle(self.primary)
                    # copy over generator information from temporary event to event
                    self._evt._generator_info = self._generator_info

                    self._station = NuRadioReco.framework.station.Station(self._station_id)
                    sim_station = NuRadioReco.framework.sim_station.SimStation(self._station_id)
                    sim_station.set_is_neutrino()
                    tmp_sim_station = tmp_station.get_sim_station()
                    self._shower_ids_of_sub_event = []
                    for iCh in indices:
                        ch_uid = channel_identifiers[iCh]
                        shower_id = ch_uid[1]
                        if shower_id not in self._shower_ids_of_sub_event:
                            self._shower_ids_of_sub_event.append(shower_id)
                        sim_station.add_channel(tmp_sim_station.get_channel(ch_uid))
                        efield_uid = ([ch_uid[0]], ch_uid[1], ch_uid[2])  # the efield unique identifier has as first parameter an array of the channels it is valid for
                        for efield in tmp_sim_station.get_electric_fields():
                            if efield.get_unique_identifier() == efield_uid:
                                sim_station.add_electric_field(efield)

                    if particle_mode:
                        # add showers that contribute to this (sub) event to event structure
                        for shower_id in self._shower_ids_of_sub_event:
                            self._evt.add_sim_shower(self._evt_tmp.get_sim_shower(shower_id))
                    self._station.set_sim_station(sim_station)
                    self._station.set_station_time(self._evt_time)
                    self._evt.set_station(self._station)
                    if bool(self._cfg['signal']['zerosignal']):
                        self._increase_signal(None, 0)

                    logger.debug("performing detector simulation")
                    self._simulate_detector_response()
                    if not self._station.has_triggered():
                        continue

                    event_group_has_triggered = True
                    triggered_showers[self._station_id].extend(self._get_shower_index(self._shower_ids_of_sub_event))
                    self._calculate_signal_properties()

                    global_shower_indices = self._get_shower_index(self._shower_ids_of_sub_event)
                    local_shower_index = np.atleast_1d(np.squeeze(np.argwhere(np.isin(event_indices, global_shower_indices, assume_unique=True))))
                    self._save_triggers_to_hdf5(sg, local_shower_index, global_shower_indices)
                    if self._outputfilenameNuRadioReco is not None:
                        self._write_nur_file()
                # end sub events loop

                # add local sg array to output data structure if any
                if event_group_has_triggered:
                    if self._station_id not in self._mout_groups:
                        self._mout_groups[self._station_id] = {}
                    for key in sg:
                        if key not in self._mout_groups[self._station_id]:
                            self._mout_groups[self._station_id][key] = list(sg[key])
                        else:
                            self._mout_groups[self._station_id][key].extend(sg[key])
                # print(self._mout_groups[self._station_id]['travel_times'])
                self._detSimTime += time.time() - t1

            # end station loop

        # end event group loop

        # Create trigger structures if there are no triggering events.
        # This is done to ensure that files with no triggering n_events
        # merge properly.
#         self._create_empty_multiple_triggers()

        # save simulation run in hdf5 format (only triggered events)
        t5 = time.time()
        self._write_output_file()
        if self._outputfilenameNuRadioReco is not None:
            self._eventWriter.end()
            logger.debug("closing nur file")

        try:
            self.calculate_Veff()
        except:
            logger.error("error in calculating effective volume")

        t_total = time.time() - t_start
        self._outputTime = time.time() - t5

        output_NuRadioRecoTime = "Timing of NuRadioReco modules \n"
        ts = []
        for iM, (name, instance, kwargs) in enumerate(self._evt.iter_modules(self._station.get_id())):
            ts.append(instance.run.time[instance])
        ttot = np.sum(np.array(ts))
        for i, (name, instance, kwargs) in enumerate(self._evt.iter_modules(self._station.get_id())):
            t = NuRadioMC.simulation.simulation_base.pretty_time_delta(ts[i])
            trel = 100.*ts[i] / ttot
            output_NuRadioRecoTime += f"{name}: {t} {trel:.1f}%\n"
        logger.status(output_NuRadioRecoTime)

        logger.status("{:d} events processed in {} = {:.2f}ms/event ({:.1f}% input, {:.1f}% ray tracing, {:.1f}% askaryan, {:.1f}% detector simulation, {:.1f}% output, {:.1f}% weights calculation)".format(self._n_showers,
                                                                                         NuRadioMC.simulation.simulation_base.pretty_time_delta(t_total), 1.e3 * t_total / self._n_showers,
                                                                                         100 * self._input_time / t_total,
                                                                                         100 * (self._rayTracingTime - self._askaryan_time) / t_total,
                                                                                         100 * self._askaryan_time / t_total,
                                                                                         100 * self._detSimTime / t_total,
                                                                                         100 * self._outputTime / t_total,
                                                                                         100 * self._weightTime / t_total))
        triggered = remove_duplicate_triggers(self._mout['triggered'], self._fin['event_group_ids'])
        n_triggered = np.sum(triggered)
        return n_triggered

    def _calculate_emitter_output(self):
        pass

    def _get_shower_index(self, shower_id):
        if hasattr(shower_id, "__len__"):
            return np.array([self._shower_index_array[x] for x in shower_id])
        else:
            return self._shower_index_array[shower_id]

    def _is_simulate_noise(self):
        """
        returns True if noise should be added
        """
        return bool(self._cfg['noise'])

    def _is_in_fiducial_volume(self):
        """
        checks wether a vertex is in the fiducial volume

        if the fiducial volume is not specified in the input file, True is returned (this is required for the simulation
        of pulser calibration measuremens)
        """
        tt = ['fiducial_rmin', 'fiducial_rmax', 'fiducial_zmin', 'fiducial_zmax']
        has_fiducial = True
        for t in tt:
            if not t in self._fin_attrs:
                has_fiducial = False
        if not has_fiducial:
            return True

        r = (self._shower_vertex[0] ** 2 + self._shower_vertex[1] ** 2) ** 0.5
        if r >= self._fin_attrs['fiducial_rmin'] and r <= self._fin_attrs['fiducial_rmax']:
            if self._shower_vertex[2] >= self._fin_attrs['fiducial_zmin'] and self._shower_vertex[2] <= self._fin_attrs['fiducial_zmax']:
                return True
        return False

    def _increase_signal(self, channel_id, factor):
        """
        increase the signal of a simulated station by a factor of x
        this is e.g. used to approximate a phased array concept with a single antenna

        Parameters
        ----------
        channel_id: int or None
            if None, all available channels will be modified
        """
        if channel_id is None:
            for electric_field in self._station.get_sim_station().get_electric_fields():
                electric_field.set_trace(electric_field.get_trace() * factor, sampling_rate=electric_field.get_sampling_rate())

        else:
            sim_channels = self._station.get_sim_station().get_electric_fields_for_channels([channel_id])
            for sim_channel in sim_channels:
                sim_channel.set_trace(sim_channel.get_trace() * factor, sampling_rate=sim_channel.get_sampling_rate())


    def _check_vertex_times(self):

        if 'vertex_times' in self._fin:
            return True
        else:
            warn_msg = 'The input file does not include vertex times. '
            warn_msg += 'Vertices from the same event will not be time-ordered.'
            logger.warning(warn_msg)
            return False

    def _calculate_signal_properties(self):
        if self._station.has_triggered():
            self._channelSignalReconstructor.run(self._evt, self._station, self._det)
            amplitudes = np.zeros(self._station.get_number_of_channels())
            amplitudes_envelope = np.zeros(self._station.get_number_of_channels())
            for channel in self._station.iter_channels():
                amplitudes[channel.get_id()] = channel.get_parameter(chp.maximum_amplitude)
                amplitudes_envelope[channel.get_id()] = channel.get_parameter(chp.maximum_amplitude_envelope)
            self._output_maximum_amplitudes[self._station.get_id()].append(amplitudes)
            self._output_maximum_amplitudes_envelope[self._station.get_id()].append(amplitudes_envelope)

    def get_Vrms(self):
        return self._Vrms

    def get_sampling_rate(self):
        return 1. / self._dt

    def get_bandwidth(self):
        return self._bandwidth

    def _check_if_was_pre_simulated(self):
        """
        checks if the same detector was simulated before (then we can save the ray tracing part)
        """
        self._was_pre_simulated = False
        if 'detector' in self._fin_attrs:
            with open(self._detectorfile, 'r') as fdet:
                if fdet.read() == self._fin_attrs['detector']:
                    self._was_pre_simulated = True
                    logger.debug("the simulation was already performed with the same detector")
        return self._was_pre_simulated

    def _create_sim_station(self):
        """
        created an empyt sim_station object
        """
        # create NuRadioReco event structure
        self._sim_station = NuRadioReco.framework.sim_station.SimStation(self._station_id)
        self._sim_station.set_is_neutrino()

    def _create_sim_shower(self):
        """
        creates a sim_shower object and saves the meta arguments such as neutrino direction, shower energy and self.input_particle[flavor]
        """
        # create NuRadioReco event structure
        self._sim_shower = NuRadioReco.framework.radio_shower.RadioShower(self._shower_ids[self._shower_index])
        # save relevant neutrino properties
        self._sim_shower[shp.zenith] = self.input_particle[simp.zenith]
        self._sim_shower[shp.azimuth] = self.input_particle[simp.azimuth]
        self._sim_shower[shp.energy] = self._fin['shower_energies'][self._shower_index]
        self._sim_shower[shp.flavor] = self.input_particle[simp.flavor]
        self._sim_shower[shp.interaction_type] = self.input_particle[simp.interaction_type]
        self._sim_shower[shp.vertex] = self.input_particle[simp.vertex]
        self._sim_shower[shp.vertex_time] = self._vertex_time
        self._sim_shower[shp.type] = self._fin['shower_type'][self._shower_index]
        # TODO direct parent does not necessarily need to be the primary in general, but full
        # interaction chain is currently not populated in the input files.
        self._sim_shower[shp.parent_id] = self.primary.get_id()



    def calculate_Veff(self):
        # calculate effective
        triggered = remove_duplicate_triggers(self._mout['triggered'], self._fin['event_group_ids'])
        n_triggered = np.sum(triggered)
        n_triggered_weighted = np.sum(self._mout['weights'][triggered])
        n_events = self._fin_attrs['n_events']
        logger.status(f'fraction of triggered events = {n_triggered:.0f}/{n_events:.0f} = {n_triggered / self._n_showers:.3f} (sum of weights = {n_triggered_weighted:.2f})')

        V = self._fin_attrs['volume']
        Veff = V * n_triggered_weighted / n_events
        logger.status(f"Veff = {Veff / units.km ** 3:.4g} km^3, Veffsr = {Veff * 4 * np.pi/units.km**3:.4g} km^3 sr")

    def _calculate_polarization_vector(self):
        """ calculates the polarization vector in spherical coordinates (eR, eTheta, ePhi)
        """
        if self._cfg['signal']['polarization'] == 'auto':
            polarization_direction = np.cross(self._launch_vector, np.cross(self._shower_axis, self._launch_vector))
            polarization_direction /= np.linalg.norm(polarization_direction)
            cs = cstrans.cstrafo(*hp.cartesian_to_spherical(*self._launch_vector))
            return cs.transform_from_ground_to_onsky(polarization_direction)
        elif self._cfg['signal']['polarization'] == 'custom':
            ePhi = float(self._cfg['signal']['ePhi'])
            eTheta = (1 - ePhi ** 2) ** 0.5
            v = np.array([0, eTheta, ePhi])
            return v / np.linalg.norm(v)
        else:
            msg = "{} for config.signal.polarization is not a valid option".format(self._cfg['signal']['polarization'])
            logger.error(msg)
            raise ValueError(msg)

    def _calculate_station_barycenter(self):
        station_barycenter = np.zeros((len(self._station_ids), 3))
        for iSt, station_id in enumerate(self._station_ids):
            pos = []
            for channel_id in range(self._det.get_number_of_channels(station_id)):
                pos.append(self._det.get_relative_position(station_id, channel_id))
            station_barycenter[iSt] = np.mean(np.array(pos), axis=0) + self._det.get_absolute_position(station_id)
        return station_barycenter

    def _calculate_particle_weights(
            self,
            evt_indices
    ):
        self._read_input_particle_properties(
            self._primary_index)  # this sets the self.input_particle for self._primary_index
        # calculate the weight for the primary particle
        self.primary = self.input_particle
        if self._cfg['weights']['weight_mode'] == "existing":
            if "weights" in self._fin:
                self._mout['weights'] = self._fin["weights"]
            else:
                logger.error(
                    "config file specifies to use weights from the input hdf5 file but the input file does not contain this information.")
        elif self._cfg['weights']['weight_mode'] is None:
            self.primary[simp.weight] = 1.
        else:
            self.primary[simp.weight] = get_weight(self.primary[simp.zenith],
                                                   self.primary[simp.energy],
                                                   self.primary[simp.flavor],
                                                   mode=self._cfg['weights']['weight_mode'],
                                                   cross_section_type=self._cfg['weights']['cross_section_type'],
                                                   vertex_position=self.primary[simp.vertex],
                                                   phi_nu=self.primary[simp.azimuth])
        # all entries for the event for this primary get the calculated primary's weight
        self._mout['weights'][evt_indices] = self.primary[simp.weight]

    def _distance_cut_channel(
            self,
            shower_energy_sum,
            x1,
            x2
    ):
        """
        Checks if the channel fulfills the distance cut criterium.
        Returns True if the channel is within the maximum distance
        (and should therefore be simulated) and False otherwise

        Parameters
        ----------
        shower_energy_sum: flaot
            sum of the energies of all sub-showers in this event
        x1: array of floats
            position of the shower
        x2: array of floats
            position of the channel

        Returns
        -------

        """
        distance_cut = self._get_distance_cut(shower_energy_sum)
        distance = np.linalg.norm(x1 - x2)
        if distance > distance_cut:
            logger.debug('A distance speed up cut has been applied')
            logger.debug('Shower energy: {:.2e} eV'.format(self._fin['shower_energies'][self._shower_index] / units.eV))
            logger.debug('Distance cut: {:.2f} m'.format(distance_cut / units.m))
            logger.debug('Distance to vertex: {:.2f} m'.format(distance / units.m))
        return distance <= distance_cut