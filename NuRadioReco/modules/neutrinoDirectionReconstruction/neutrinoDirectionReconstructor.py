import scipy
from radiotools import helper as hp
import radiotools.coordinatesystems as cstrans
import matplotlib.pyplot as plt
import numpy as np
from NuRadioReco.utilities import fft
from NuRadioReco.framework.parameters import stationParameters as stnp
from NuRadioReco.framework.parameters import showerParameters as shp
from NuRadioReco.modules.neutrinoDirectionReconstruction import analytic_pulse
from NuRadioMC.utilities import medium
from scipy import signal
from scipy import optimize as opt
from scipy.spatial.transform import Rotation
import datetime
import math
from NuRadioReco.utilities import units
import datetime
import logging
import pickle
logger = logging.getLogger("neutrinoDirectionReconstructor")
logger.setLevel(logging.DEBUG)

class neutrinoDirectionReconstructor:

    def __init__(self):
        pass

    def begin(
            self, station, det, event, shower_ids, use_channels=[6, 14], ch_Vpol = 6,
            ch_Hpol = 8,sim = True, single_pulse_fit = False, PA_cluster_channels= [0,1,2,3,7,8],
            Hpol_channels = [7,8], window_Vpol = [-10, +50], window_Hpol = [10, 40],
            PA_channels = [0,1,2,3], Vrms_Hpol = 8.2 * units.mV, Vrms_Vpol = 8.2 * units.mV,
            passband = [50*units.MHz, 700*units.MHz],
            template = True, icemodel='greenland_simple', att_model='GL1', propagation_config=None,
            debug_formats='.pdf'):
        """
        begin method. This function is executed before the event loop.
        We do not use this function for the reconsturctions. But only to determining uncertainties.
        """
        self._sim_vertex = sim
        self._Vrms = Vrms_Vpol
        #print("self Vrms", self._Vrms)
        self._Vrms_Hpol = Vrms_Hpol
        self._station = station
        self._use_channels = use_channels
        self._det = det
        self._ice_model = icemodel
        self._att_model = att_model
        self._prop_config = propagation_config
        self._passband = passband
        for channel in station.iter_channels():
            self._sampling_rate = channel.get_sampling_rate()
            break
        simulated_energy = 0
        for i in np.unique(shower_ids):
            simulated_energy += event.get_sim_shower(i)[shp.energy]

        shower_id = shower_ids[0]
        self._simulated_azimuth = event.get_sim_shower(shower_id)[shp.azimuth]
        self._simulated_zenith = event.get_sim_shower(shower_id)[shp.zenith]
        if sim:
            vertex =event.get_sim_shower(shower_id)[shp.vertex]
        else:
            vertex = station[stnp.nu_vertex]
        simulation = analytic_pulse.simulation(template, vertex)
        if sim: rt = ['direct', 'refracted', 'reflected'].index(self._station[stnp.raytype_sim]) + 1
        if not sim: rt = ['direct', 'refracted', 'reflected'].index(self._station[stnp.raytype]) + 1
        simulation.begin(
            det, station, use_channels, raytypesolution = rt, ch_Vpol = ch_Vpol,
            Hpol_channels = Hpol_channels,
            ice_model=self._ice_model, att_model=self._att_model,
            passband=self._passband, propagation_config=self._prop_config
        )#[1, 2, 3] [direct, refracted, reflected]
        self._launch_vector_sim, view =  simulation.simulation(
            det, station, vertex[0],vertex[1], vertex[2], self._simulated_zenith,
            self._simulated_azimuth, simulated_energy, use_channels,
            first_iter = True)[2:4]
        self._simulation = simulation
        self._single_pulse_fit = single_pulse_fit
        self._PA_cluster_channels = PA_cluster_channels
        self._Hpol_channels = Hpol_channels
        self._window_Vpol = window_Vpol
        self._window_Hpol = window_Hpol
        self._PA_channels = PA_channels
        self._debug_formats = debug_formats
        return self._launch_vector_sim, view

    def run(self, event, station, det, shower_ids = None,
            use_channels=[6, 14], filenumber = 1, PA_channels = [0,1,2,3],
            single_pulse = False, debug_plots = False, template = False,
            sim_vertex = True, Vrms_Vpol = 0.01, Vrms_Hpol = 0.01,
            only_simulation = False, ch_Vpol = 6, ch_Hpol = 13,
            full_station = True, brute_force = True, fixed_timing = False,
            restricted_input = True, starting_values = False,
            debugplots_path = None, PA_cluster_channels = [0,1,2,3, 7,8],
            Hpol_channels = [7,8], window_Hpol = [10, +40],
            window_Vpol = [-10, +50], single_pulse_fit = False,
            Hpol_lower_band = 50,  Hpol_upper_band = 700):

        """
        Module to reconstruct the direction of the event.
        event: Event
            The event to reconstruct the direction
        station: Station
            The station used to reconstruct the direction
        shower_ids: list
            list of shower ids for the event, only used if simulated vertex is used for input. Default shower_ids = None.
        use_channels: list
            list of channel ids used for the reconstruction
        filenumber: int
            This is only to link the debug plots to correct file. Default filenumber = 1.
        single_pulse: Boolean
            if True,
        debug_plots: Boolean
            if True, debug plots are produced. Default debug_plots = False.
        debugplots_path: str
            Path to store the debug plots. Default = None.
        template: Boolean
            If True, ARZ templates are used for the reconstruction. If False, a parametrization is used. 'Alvarez2009' and 'ARZ average' is available. Default template = False.
        sim_vertex: Boolean
            If True, the simulated vertex is used. This is for debugging purposes. Default sim_vertex = False.
        Vrms: float
            Noise root mean squared. Default = 0.0114 V
        only_simulation: Boolean
            if True, the fit is not performed but only the simulated values are compared with the data. This is just for debugging purposes. Default only_simulation = False.
        ch_Vpol: int
            channel id of the Vpol used to determine reference timing. Should be the top Vpol of the phased array. Default ch_Vpol = 6.
        ch_Hpol: int
            channel id of Hpol nearest to the Vpol. Timing of the Hpol is determined using the vertex position, because difference is only 1 m. Default ch_Vpol = 13.
        full_station: Boolean
            If True, all the raytypes in the list use_channels are used. If False, only the triggered pulse is used. Default full_station = True.
        brute_force: Boolean
            If True, brute force method is used. If False, minimization is used. Default brute_force = True.
        fixed_timing: Boolean
            If True, the known positions of the pulses are used calculated using the vertex position. Only allowed when sim_vertex is True. If False, an extra correlation is used to find the exact pulse position. Default fixed_timing = False.
        restricted_input: Boolean
            If True, a reconstruction is performed a few degrees around the MC values. This is (of course) only for simulations. Default restricted_input = False.
        starting_values: Boolean
            if True, first the channels of the phased array are used to get starting values for the viewing angle and the energy.
        debugplots_Path: str
            path to store plots.
        PA_cluster_channels:
        single_pulse_fit: Boolean
            if True, the viewing angle and energy are fitted with a PA Vpol and the polarization is fitted using an Hpol. Default single_pulse_fit = False.

        """

        station.set_is_neutrino()
        self._Vrms = Vrms_Vpol
        self._Vrms_Hpol = Vrms_Hpol
        self._station = station
        self._use_channels = use_channels
        self._det = det
        self._model_sys = 0.0 ## test amplitude effect of systematics on the model
        self._PA_cluster_channels = PA_cluster_channels
        self._Hpol_channels = Hpol_channels
        self._single_pulse_fit = single_pulse_fit
        self._PA_channels = PA_channels
        self._sim_vertex = sim_vertex
        if single_pulse_fit:
            starting_values = True


        channl = station.get_channel(use_channels[0])
        n_samples = channl.get_number_of_samples()
        self._sampling_rate = channl.get_sampling_rate()
        sampling_rate = self._sampling_rate

        if sim_vertex:
            shower_id = shower_ids[0]
            reconstructed_vertex = event.get_sim_shower(shower_id)[shp.vertex]
            print("simulated vertex direction reco", event.get_sim_shower(shower_id)[shp.vertex])
        else:
            reconstructed_vertex = station[stnp.nu_vertex]

            print("reconstructed vertex direction reco", reconstructed_vertex)
        self._vertex_azimuth = np.arctan2(reconstructed_vertex[1], reconstructed_vertex[0])
        ice = medium.get_ice_model(self._ice_model)
        self._cherenkov_angle = np.arccos(1 / ice.get_index_of_refraction(reconstructed_vertex))

        if self._station.has_sim_station():
            shower_id = shower_ids[0]
            sim_station = True
            simulated_zenith = event.get_sim_shower(shower_id)[shp.zenith]
            simulated_azimuth = event.get_sim_shower(shower_id)[shp.azimuth]
            self._simulated_azimuth = simulated_azimuth
            simulated_energy = 0
            for i, shower_id in enumerate(np.unique(shower_ids)):
                if (event.get_sim_shower(shower_id)[shp.type] != "em"):
                    simulated_energy += event.get_sim_shower(shower_id)[shp.energy]
                    print("simulated energy", simulated_energy)
            self.__simulated_energy =simulated_energy
            simulated_vertex = event.get_sim_shower(shower_id)[shp.vertex]
            ### values for simulated vertex and simulated direction
            simulation = analytic_pulse.simulation(template, simulated_vertex)
            rt = ['direct', 'refracted', 'reflected'].index(self._station[stnp.raytype_sim]) + 1
            simulation.begin(
                det, station, use_channels, raytypesolution = rt,
                ch_Vpol = ch_Vpol, Hpol_channels = Hpol_channels,
                Hpol_lower_band = Hpol_lower_band, Hpol_upper_band = Hpol_upper_band,
                ice_model=self._ice_model, att_model=self._att_model,
                passband=self._passband, propagation_config=self._prop_config)
            tracsim, timsim, lv_sim, vw_sim, a, pol_sim = simulation.simulation(
                det, station, event.get_sim_shower(shower_id)[shp.vertex][0],
                event.get_sim_shower(shower_id)[shp.vertex][1],
                event.get_sim_shower(shower_id)[shp.vertex][2],
                simulated_zenith, simulated_azimuth, simulated_energy,
                use_channels, first_iter = True)
            if pol_sim is None: # occasionally (if the vertex position is wrong), no solution may exist for the sim vertex and the given ray type.
                if rt == 1:
                    sim_rt = 2
                elif rt == 2:
                    sim_rt = 1
                else: # this probably shouldn't ever happen?
                    logger.warning("Couldn't determine polarization / viewing angle for sim_station. Skipping...")
                    sim_rt = None
                logger.warning(
                    "The reconstructed ray type is {}, but for the simulated vertex, no such ray solution exists. Using {} instead.".format(
                        rt, sim_rt
                    ))
                simulation._raytypesolution = sim_rt
                tracsim, timsim, lv_sim, vw_sim, a, pol_sim = simulation.simulation(
                    det, station, event.get_sim_shower(shower_id)[shp.vertex][0],
                    event.get_sim_shower(shower_id)[shp.vertex][1],
                    event.get_sim_shower(shower_id)[shp.vertex][2],
                    simulated_zenith, simulated_azimuth, simulated_energy,
                    use_channels, first_iter = True)
            # simulation._raytypesolution = rt # revert to reconstructed ray type for reconstruction!
            if pol_sim is None: # for some reason, didn't manage to obtain simulated vw / polarization angle
                pol_sim = np.nan * np.ones(3) # we still set them, so the debug plots don't fail
                vw_sim = np.nan
            self._launch_vector_sim = lv_sim # not used?
            logger.debug(
                "Simulated viewing angle: {:.1f} deg / Polarization angle: {:.1f} deg".format(
                    vw_sim / units.deg, np.arctan2(pol_sim[2], pol_sim[1]) / units.deg
                )
            )

            ## check SNR of channels
            SNR = []
            for ich, channel in enumerate(station.get_sim_station().iter_channels()):
                # logger.debug("channel {}, SNR {}".format(channel.get_id(),(abs(min(channel.get_trace())) + max(channel.get_trace())) / (2*self._Vrms) ))
                if channel.get_id() in use_channels:
                    SNR.append((abs(abs(min(channel.get_trace()))) + max(channel.get_trace())) / (2*self._Vrms))



        simulation = analytic_pulse.simulation(template, reconstructed_vertex) ### if the templates are used, than the templates for the correct distance are loaded
        if not sim_vertex:
            rt = ['direct', 'refracted', 'reflected'].index(self._station[stnp.raytype]) + 1 ## raytype from the triggered pulse

        simulation.begin(
            det, station, use_channels, raytypesolution = rt,
            ch_Vpol = ch_Vpol, Hpol_channels = Hpol_channels,
            Hpol_lower_band = Hpol_lower_band, Hpol_upper_band = Hpol_upper_band,
            ice_model=self._ice_model, att_model=self._att_model,
            passband=self._passband, propagation_config=self._prop_config
            )
        self._simulation = simulation
        if station.has_sim_station():

            print("simulated vertex", simulated_vertex)
            print('reconstructed', reconstructed_vertex)

            self._launch_vector = simulation.simulation(
                det, station, *reconstructed_vertex, np.pi/2, 0, 1e17,
                use_channels, first_iter=True)[2]
            #### values for reconstructed vertex and simulated direction
            if sim_station:
                # traces_sim, timing_sim, self._launch_vector_sim, viewingangles_sim, rayptypes, a = simulation.simulation(
                #     det, station, event.get_sim_shower(shower_id)[shp.vertex][0],
                #     event.get_sim_shower(shower_id)[shp.vertex][1],
                #     event.get_sim_shower(shower_id)[shp.vertex][2],
                #     simulated_zenith, simulated_azimuth, simulated_energy, use_channels, first_iter = True)


                fsimsim = self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], event.get_sim_shower(shower_id)[shp.vertex][0], event.get_sim_shower(shower_id)[shp.vertex][1], event.get_sim_shower(shower_id)[shp.vertex][2], minimize =  True, first_iter = True, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station, sim = True)
                all_fsimsim = self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], event.get_sim_shower(shower_id)[shp.vertex][0], event.get_sim_shower(shower_id)[shp.vertex][1], event.get_sim_shower(shower_id)[shp.vertex][2], minimize =  False, first_iter = True, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station, sim = True)[3]
                tracsim = self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], event.get_sim_shower(shower_id)[shp.vertex][0], event.get_sim_shower(shower_id)[shp.vertex][1], event.get_sim_shower(shower_id)[shp.vertex][2], minimize =  False, first_iter = True, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station, sim = True)[0]
            #     #tracsim_recvertex = self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], minimize =  False, first_iter = True,ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station, sim = True)[0]

                fsim = self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], event.get_sim_shower(shower_id)[shp.vertex][0], event.get_sim_shower(shower_id)[shp.vertex][1], event.get_sim_shower(shower_id)[shp.vertex][2], minimize =  True, first_iter = True, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station, sim = True)

                all_fsim = self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], event.get_sim_shower(shower_id)[shp.vertex][0], event.get_sim_shower(shower_id)[shp.vertex][1], event.get_sim_shower(shower_id)[shp.vertex][2], minimize =  False, first_iter = True, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station, sim = True)[3]
                print("Chi2 values for simulated direction and with/out simulated vertex are {}/{}".format(fsimsim, fsim))

                sim_reduced_chi2_Vpol = self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], event.get_sim_shower(shower_id)[shp.vertex][0], event.get_sim_shower(shower_id)[shp.vertex][1], event.get_sim_shower(shower_id)[shp.vertex][2], minimize =  False, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station, sim = True)[4][0]


                sim_reduced_chi2_Hpol = self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], event.get_sim_shower(shower_id)[shp.vertex][0], event.get_sim_shower(shower_id)[shp.vertex][1], event.get_sim_shower(shower_id)[shp.vertex][2], minimize =  False, first_iter = True, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station, sim = True)[4][1]
            #     self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], minimize =  False, first_iter = True, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station)

                tracsim_recvertex = self.minimizer([simulated_zenith,simulated_azimuth, np.log10(simulated_energy)], reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], minimize =  False, first_iter = True,ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station)[0]

            signal_zenith, signal_azimuth = hp.cartesian_to_spherical(*self._launch_vector)
            sig_dir = hp.spherical_to_cartesian(signal_zenith, signal_azimuth)

        if 1:#

            # cherenkov = self._cherenkov_angle ## cherenov angle
            if starting_values:
                viewing_start = viewangles[np.argmin(L)] - np.deg2rad(2)
                viewing_end = viewangles[np.argmin(L)] + np.deg2rad(2)
                energy_start = 10**energies[np.argmin(L)]
            # else: #vw_sim not defined unless we take it from simulation
            #     viewing_start = vw_sim - np.deg2rad(2)
            #     viewing_end = vw_sim + np.deg2rad(2)
            #     energy_start = simulated_energy

            viewing_start = self._cherenkov_angle - np.deg2rad(15) # 15 degs
            viewing_end = self._cherenkov_angle + np.deg2rad(15)
            d_viewing_grid = .5 * units.deg # originally .5 deg
            energy_start = 1e17 * units.eV
            energy_end = 1e19 * units.eV + 1e14 * units.eV
            d_log_energy = .5
            # energy_start = simulated_energy / 3
            # energy_end = simulated_energy * 3
            theta_start = np.deg2rad(-180) #-180
            theta_end =  np.deg2rad(180) #180

            d_theta_grid = 5 * units.deg # originally 1 degree

            cop = datetime.datetime.now()
            if station.has_sim_station(): print("SIMULATED DIRECTION {} {}".format(np.rad2deg(simulated_zenith), np.rad2deg(simulated_azimuth)))

            if only_simulation:
                print("no reconstructed is performed. The script is tested..")
            elif brute_force and not restricted_input:# restricted_input:
                if starting_values:
                    results2 = opt.brute(self.minimizer, ranges=(slice(viewing_start, viewing_end, np.deg2rad(.5)), slice(theta_start, theta_end, np.deg2rad(1)), slice(np.log10(energy_start) - .15, np.log10(energy_start) + .15, .1)), full_output = True, finish = opt.fmin , args = (reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], True, False, False, True, False, ch_Vpol, ch_Hpol, full_station))
                    results1 = opt.brute(self.minimizer, ranges=(slice(viewing_start, viewing_end, np.deg2rad(.5)), slice(theta_start, theta_end, np.deg2rad(1)), slice(np.log10(energy_start) - .15, np.log10(energy_start) + .15, .1)), full_output = True, finish = opt.fmin , args = (reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], True, False, False, True, False, ch_Vpol, ch_Hpol, full_station))
                    if results2[1] < results1[1]:
                        results = results2
                    else:
                        results = results1
                else:
                    results = opt.brute(
                        self.minimizer,
                        ranges=(
                            slice(viewing_start, viewing_end, d_viewing_grid),
                            slice(theta_start, theta_end, d_theta_grid),
                            slice(np.log10(energy_start), np.log10(energy_end), d_log_energy)
                        ), full_output = True, finish = opt.fmin,
                        args = (
                            reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2],
                            True, False, False, True, False, ch_Vpol, ch_Hpol, full_station
                        )
                    )

            elif restricted_input:
                zenith_start =  simulated_zenith - np.deg2rad(2)
                zenith_end =simulated_zenith +  np.deg2rad(2)
                azimuth_start =simulated_azimuth - np.deg2rad(2)
                azimuth_end = simulated_azimuth + np.deg2rad(2)
                energy_start = np.log10(simulated_energy) - 1
                energy_end = np.log10(simulated_energy) + 1
                results = opt.brute(self.minimizer, ranges=(slice(zenith_start, zenith_end, np.deg2rad(.5)), slice(azimuth_start, azimuth_end, np.deg2rad(.5)), slice(energy_start, energy_end, .1)), finish = opt.fmin, full_output = True, args = (reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], True, False, False, False, False, ch_Vpol, ch_Hpol, full_station))

            print('start datetime', cop)
            print("end datetime", datetime.datetime.now() - cop)
            # print("cache statistics for analytic_pulse ray tracer")
            # print(self._simulation._raytracer.cache_info())
            vw_grid = results[-2]
            chi2_grid = results[-1]
            # np.save("{}/grid_{}".format(debugplots_path, filenumber), vw_grid)
            # np.save("{}/chi2_{}".format(debugplots_path, filenumber), chi2_grid)
            ###### GET PARAMETERS #########

            if only_simulation:
                rec_zenith = simulated_zenith
                rec_azimuth = simulated_azimuth
                rec_energy = simulated_energy

            elif brute_force and not restricted_input:
                rotation_matrix = hp.get_rotation(sig_dir, np.array([0, 0,1]))
                cherenkov_angle = results[0][0]
                angle = results[0][1]

                # p3 = np.array([np.sin(cherenkov_angle)*np.cos(angle), np.sin(cherenkov_angle)*np.sin(angle), np.cos(cherenkov_angle)])
                # p3 = rotation_matrix.dot(p3)
                # global_az = hp.cartesian_to_spherical(p3[0], p3[1], p3[2])[1]
                # global_zen = hp.cartesian_to_spherical(p3[0], p3[1], p3[2])[0]
                # global_zen = np.deg2rad(180) - global_zen

                rec_zenith, rec_azimuth = self._transform_angles(cherenkov_angle, angle)

                # rec_zenith = global_zen
                # rec_azimuth = global_az
                rec_energy = 10**results[0][2]

            elif restricted_input:
                rec_zenith = results[0][0]
                rec_azimuth = results[0][1]
                rec_energy = 10**results[0][2]

            ###### PRINT RESULTS ###############
            if station.has_sim_station():
                print("         simulated energy {}".format(simulated_energy))
                print("         simulated zenith {}".format(np.rad2deg(simulated_zenith)))
                print("         simulated azimuth {}".format(np.rad2deg(simulated_azimuth)))


            print("     reconstructed energy {}".format(rec_energy))
            print("     reconstructed zenith = {}".format(np.rad2deg(rec_zenith)))
            print("     reconstructed azimuth = {}".format(np.rad2deg(self.transform_azimuth(rec_azimuth))))


            ## get the traces for the reconstructed energy and direction
            reconstruction_output = self.minimizer([rec_zenith, rec_azimuth, np.log10(rec_energy)], reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], minimize = False, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station)
            tracrec = reconstruction_output[0]
            fit_reduced_chi2_Vpol = reconstruction_output[4][0]
            fit_reduced_chi2_Hpol = reconstruction_output[4][1]
            channels_overreconstructed = reconstruction_output[5]
            extra_channel = reconstruction_output[6]
            chi2_dict = reconstruction_output[3]

            fminfit = self.minimizer([rec_zenith, rec_azimuth, np.log10(rec_energy)], reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], minimize =  True, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station)

            all_fminfit = self.minimizer([rec_zenith, rec_azimuth, np.log10(rec_energy)], reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], minimize =  False, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station)[3]
            bounds = ((14, 20))
            method = 'BFGS'
            results = scipy.optimize.minimize(self.minimizer, [14],method = method, args=(reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], True, False, False,False, [simulated_zenith, simulated_azimuth], ch_Vpol, ch_Hpol, True, False), bounds= bounds)
            if station.has_sim_station(): fmin_simdir_recvertex = self.minimizer([simulated_zenith, simulated_azimuth, results.x[0]], reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], minimize = True, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station)

            ### values for reconstructed vertex and reconstructed direction
            traces_rec, timing_rec, launch_vector_rec, viewingangle_rec, a, pol_rec =  simulation.simulation( det, station, reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], rec_zenith, rec_azimuth, rec_energy, use_channels, first_iter = True)

            print("make debug plots....")
            if debug_plots:
                linewidth = 2
                tracdata = reconstruction_output[1]
                timingdata = reconstruction_output[2]
                timingsim = self.minimizer(
                    [simulated_zenith, simulated_azimuth, np.log10(simulated_energy)],
                    *event.get_sim_shower(shower_id)[shp.vertex],
                    first_iter = True, minimize = False, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol,
                     full_station = full_station, sim=True)[2]

                timingsim_recvertex = self.minimizer([simulated_zenith, simulated_azimuth, np.log10(simulated_energy)], reconstructed_vertex[0], reconstructed_vertex[1], reconstructed_vertex[2], first_iter = True, minimize = False, ch_Vpol = ch_Vpol, ch_Hpol = ch_Hpol, full_station = full_station)[2]
                fig, ax = plt.subplots(len(use_channels), 3, sharex=False, figsize=(16, 4*len(use_channels)))

                ich = 0
                SNRs = np.zeros((len(use_channels), 2))

                for channel in station.iter_channels():
                    channel_id = channel.get_id()
                    if channel_id in use_channels: # use channels needs to be sorted
                        sim_trace = None
                        for sim_channel in station.get_sim_station().get_channels_by_channel_id(channel_id):
                            if sim_trace is None:
                                sim_trace = sim_channel
                            else:
                                sim_trace += sim_channel


                        if len(tracdata[channel_id]) > 0:
                            # logger.debug("Plotting channel {}....".format(channel_id))
                            # logger.debug("Data trace: {:.0f} - {:.0f} ns".format(channel.get_times()[0], channel.get_times()[-1]))
                            # logger.debug("Sim trace: {:.0f} - {:.0f} ns".format(timingsim[channel_id][0][0], timingsim[channel_id][0][-1]))
                            ax[ich][0].grid()
                            ax[ich][2].grid()
                            ax[ich][0].set_xlabel("timing [ns]", )
                            ax[ich][0].plot(channel.get_times(), channel.get_trace(), lw = linewidth, label = 'data', color = 'black')

                            ax[ich][0].fill_between(timingdata[channel_id][0], tracrec[channel_id][0] - self._model_sys*tracrec[channel_id][0], tracrec[channel_id][0] + self._model_sys * tracrec[channel_id][0], color = 'green', alpha = 0.2)
                            ax[ich][2].plot( np.fft.rfftfreq(len(tracdata[channel_id][0]), 1/sampling_rate), abs(fft.time2freq( tracdata[channel_id][0], sampling_rate)), color = 'black', lw = linewidth)
                            ax[ich][0].plot(timingsim[channel_id][0], tracsim[channel_id][0], label = 'simulation', color = 'orange', lw = linewidth)
                            ax[ich][0].plot(sim_trace.get_times(), sim_trace.get_trace(), label = 'sim channel', color = 'red', lw = linewidth)

                            ax[ich][0].plot(timingsim_recvertex[channel_id][0], tracsim_recvertex[channel_id][0], label = 'simulation rec vertex', color = 'lightblue' , lw = linewidth, ls = '--')

                            # show data / simulation time windows
                            window_sim = timingsim[channel_id][0][0], timingsim[channel_id][0][-1]
                            window_rec = timingdata[channel_id][0][0], timingdata[channel_id][0][-1]
                            for t in window_sim:
                                ax[ich][0].axvline(t, color='orange', ls=':')
                            for t in window_rec:
                                ax[ich][0].axvline(t, color='green', ls=':')
                            ax[ich][0].set_xlim(np.min(window_sim+window_rec)-5, np.max(window_sim+window_rec)+5)

                            ax[ich][0].plot(timingdata[channel_id][0], tracrec[channel_id][0], label = 'reconstruction', lw = linewidth, color = 'green')
                            #ax[ich][0].plot(timingdata[channel_id][0], tracrec[channel_id][0], label = 'reconstruction', color = 'green')

                            ax[ich][2].plot( np.fft.rfftfreq(len(sim_trace.get_trace()), 1/sampling_rate), abs(fft.time2freq(sim_trace.get_trace(), sampling_rate)), lw = linewidth, color = 'red')
                            ax[ich][2].plot( np.fft.rfftfreq(len(tracsim[channel_id][0]), 1/sampling_rate), abs(fft.time2freq(tracsim[channel_id][0], sampling_rate)), lw = linewidth, color = 'orange')

                            ax[ich][2].plot( np.fft.rfftfreq(len(tracrec[channel_id][0]), 1/sampling_rate), abs(fft.time2freq(tracrec[channel_id][0], sampling_rate)), color = 'green', lw = linewidth)
                            ax[ich][2].set_xlim((0, 1))
                            ax[ich][2].set_xlabel("frequency [GHz]", )

                            ax[ich][0].legend()

                        if len(tracdata[channel_id]) > 1:
                            ax[ich][1].grid()
                            ax[ich][1].set_xlabel("timing [ns]", )
                            ax[ich][1].plot(channel.get_times(), channel.get_trace(), label = 'data', lw = linewidth, color = 'black')
                            ax[ich][2].plot(np.fft.rfftfreq(len(timingsim[channel_id][1]), 1/sampling_rate), abs(fft.time2freq(tracsim[channel_id][1], sampling_rate)), lw = linewidth, color = 'red')
                            ax[ich][2].plot( np.fft.rfftfreq(len(tracdata[channel_id][1]), 1/sampling_rate), abs(fft.time2freq(tracdata[channel_id][1], sampling_rate)), color = 'black', lw = linewidth)
                            ax[ich][1].plot(timingsim[channel_id][1], tracsim[channel_id][1], label = 'simulation', color = 'orange', lw = linewidth)
                            ax[ich][1].plot(sim_trace.get_times(), sim_trace.get_trace(), label = 'sim channel', color = 'red', lw = linewidth)
                            if 1:#channel_id in [6]:#,7,8,9]:
                                ax[ich][1].plot(timingdata[channel_id][1], tracrec[channel_id][1], label = 'reconstruction', color = 'green', lw = linewidth)
                                ax[ich][1].fill_between(timingdata[channel_id][1], tracrec[channel_id][1] - self._model_sys*tracrec[channel_id][1], tracrec[channel_id][1] + self._model_sys * tracrec[channel_id][1], color = 'green', alpha = 0.2)

                            ax[ich][2].plot( np.fft.rfftfreq(len(tracsim[channel_id][1]), 1/sampling_rate), abs(fft.time2freq(tracsim[channel_id][1], sampling_rate)), lw = linewidth, color = 'orange')
                            ax[ich][1].plot(timingsim_recvertex[channel_id][1], tracsim_recvertex[channel_id][1], label = 'simulation rec vertex', color = 'lightblue', lw = linewidth, ls = '--')

                            # show data / simulation time windows
                            window_sim = timingsim[channel_id][1][0], timingsim[channel_id][1][-1]
                            window_rec = timingdata[channel_id][1][0], timingdata[channel_id][1][-1]
                            for t in window_sim:
                                ax[ich][1].axvline(t, color='orange', ls=':')
                            for t in window_rec:
                                ax[ich][1].axvline(t, color='green', ls=':')
                            ax[ich][1].set_xlim(np.min(window_sim+window_rec)-5, np.max(window_sim+window_rec)+5)



                            ax[ich][2].plot( np.fft.rfftfreq(len(tracrec[channel_id][1]), 1/sampling_rate), abs(fft.time2freq(tracrec[channel_id][1], sampling_rate)), color = 'green', lw = linewidth, label = 'channel id {}'.format(channel_id))
                            ax[ich][2].legend()
                        for ii in range(2):
                            chi2 = chi2_dict[channel_id][ii]
                            if chi2 > 0:
                                ax[ich][ii].set_title(f'$\chi^2={chi2:.2f}$')
                            else:
                                ax[ich][ii].set_fc('grey')

                        ich += 1
                ax[0][0].legend()


                fig.tight_layout()
                fig_path = "{}/{}_fit".format(debugplots_path, filenumber, shower_id)
                logger.debug(f"output path for stored figure: {fig_path}")
                # print("output path for stored figure","{}/fit_{}.pdf".format(debugplots_path, filenumber))
                save_fig(fig, fig_path, self._debug_formats)
                plt.close('all')
                ### chi squared grid from opt.brute:
                # plt.rc('xtick',)
                # plt.rc('ytick', labelsize = 10)
                min_energy_index = np.unravel_index(np.argmin(chi2_grid), vw_grid.shape)[-1]
                extent = (
                    vw_grid[0,0,0,0] / units.deg,
                    vw_grid[0,-1,0,0] / units.deg,
                    vw_grid[1,0,0,0] / units.deg,
                    vw_grid[1,0,-1,0] / units.deg,
                )

                fig = plt.figure(figsize=(6,6))
                max_chi2_plot = np.max(np.where(chi2_grid < np.inf, chi2_grid, 0)[:,:,min_energy_index])
                vmax = np.min([4*np.min(chi2_grid), max_chi2_plot])
                plt.imshow(
                    (chi2_grid[:,:,min_energy_index].T),
                    extent=extent,
                    aspect='auto',
                    vmax=vmax,
                    origin='lower'
                )
                if restricted_input: # we did the minimization in azimuth/zenith, so should plot this
                    x_sim, y_sim = simulated_zenith / units.deg, simulated_azimuth / units.deg % 360
                    x_rec, y_rec = rec_zenith / units.deg, rec_azimuth / units.deg % 360
                    xlabel, ylabel = 'zenith [deg]', 'azimuth [deg]'
                else: # minimization in viewing angle & polarization
                    x_sim, y_sim = vw_sim / units.deg, np.arctan2(pol_sim[2], pol_sim[1]) / units.deg
                    x_rec, y_rec = viewingangle_rec / units.deg, np.arctan2(pol_rec[2], pol_rec[1]) / units.deg
                    xlabel, ylabel = 'Viewing angle [deg]', 'Polarization angle [deg]'

                plt.plot(
                    x_sim, y_sim,
                    marker='o', label='{:.1f}, {:.1f} (simulated)'.format(
                        x_sim, y_sim,
                    ), color='red', ls='none'
                )
                plt.plot(
                    x_rec, y_rec,
                    marker='x', label='{:.1f}, {:.1f} (reconstructed)'.format(
                        x_rec, y_rec
                    ), color='magenta', ms=8, mfc='magenta', ls='none'
                )
                plt.xlabel(xlabel)
                plt.ylabel(ylabel)
                plt.legend()
                plt.title("E=1e{:.1f} eV".format(vw_grid[2,0,0,min_energy_index]))
                cbar = plt.colorbar(label=r"$\chi^2$")
                vmax = cbar.vmax
                vmin = cbar.vmin
                cbar_ticks = cbar.get_ticks()
                cbar_ticks = cbar_ticks[(cbar_ticks < vmax) & (cbar_ticks > vmin)]
                cbar_ticks[0] = vmin
                tick_precision = int(np.max([0, np.min([-(np.log10(vmax-vmin)-1) // 1, 2])]))
                cbar_ticklabels = [f'{tick:.{tick_precision}f}' for tick in cbar_ticks]
                cbar_ticklabels[0] = f'{vmin:.2f} / {self.__dof}'
                cbar.set_ticks(cbar_ticks, labels=cbar_ticklabels)
                plt.tight_layout()
                save_fig(fig, "{}/{}_chi_squared".format(debugplots_path, filenumber), self._debug_formats)
                plt.close()
                #exit()


            ###### STORE PARAMTERS AND PRINT PARAMTERS #########
            station.set_parameter(stnp.extra_channels, extra_channel)
            station.set_parameter(stnp.over_rec, channels_overreconstructed)
            station.set_parameter(stnp.nu_zenith, rec_zenith)
            station.set_parameter(stnp.nu_azimuth, self.transform_azimuth(rec_azimuth))
            station.set_parameter(stnp.nu_energy, rec_energy)
            station.set_parameter(stnp.chi2, [fsim, fminfit, fsimsim, self.__dof, sim_reduced_chi2_Vpol, sim_reduced_chi2_Hpol, fit_reduced_chi2_Vpol, fit_reduced_chi2_Hpol, fmin_simdir_recvertex])
            station.set_parameter(stnp.launch_vector, [lv_sim, launch_vector_rec])
            station.set_parameter(stnp.polarization, [pol_sim, pol_rec])
            station.set_parameter(stnp.viewing_angle, [vw_sim, viewingangle_rec])
            if station.has_sim_station(): print("chi2 for simulated rec vertex {}, simulated sim vertex {} and fit {}".format(fsim, fsimsim, fminfit))#reconstructed vertex
            if station.has_sim_station():
                print("chi2 for all channels simulated rec vertex {}, simulated sim vertex {} and fit {}".format(all_fsim, all_fsimsim, all_fminfit))#reconstructed vertex
                total_chi2 = np.sum([chi2s for chi2s in chi2_dict.values()])
                logger.warning(f"Fit chi squared: {total_chi2:.2f} / {self.__dof}")
                print("launch vector for simulated {} and fit {}".format(lv_sim, launch_vector_rec))
                zen_sim = hp.cartesian_to_spherical(*lv_sim)[0]
                zen_rec = hp.cartesian_to_spherical(*launch_vector_rec)[0]
                print("launch zenith for simulated {} and fit {}".format(np.rad2deg(zen_sim), np.rad2deg(zen_rec)))
                print("polarization for simulated {} and fit {}".format(pol_sim, pol_rec))
                print("polarization angle for simulated {} and fit{}".format(np.rad2deg(np.arctan2(pol_sim[2], pol_sim[1])), np.rad2deg(np.arctan2(pol_rec[2], pol_rec[1]))))
                print("viewing angle for simulated {} and fit {}".format(np.rad2deg(vw_sim), np.rad2deg(viewingangle_rec)))
                print("reduced chi2 Vpol for simulated {} and fit {}".format(sim_reduced_chi2_Vpol, fit_reduced_chi2_Vpol))
                print("reduced chi2 Hpol for simulated {} and fit {}".format(sim_reduced_chi2_Hpol, fit_reduced_chi2_Hpol))
                print("over reconstructed channels", channels_overreconstructed)
                print("extra channels", extra_channel)
                print("L for rec vertex sim direction rec energy:", fmin_simdir_recvertex)
                print("L for reconstructed vertexy directin and energy:", fminfit)

    def transform_azimuth(self, azimuth): ## from [-180, 180] to [0, 360]
        azimuth = np.rad2deg(azimuth)
        if azimuth < 0:
            azimuth = 360 + azimuth
        return np.deg2rad(azimuth)

    def _transform_angles(self, viewing_angle, polarization_angle):
        lv = self._launch_vector
        pol = np.array([0, np.cos(polarization_angle), np.sin(polarization_angle)])
        cs = cstrans.cstrafo(*hp.cartesian_to_spherical(*lv))
        pol_cartesian = cs.transform_from_onsky_to_ground(pol)
        rotation_axis = np.cross(lv, pol_cartesian)
        rot = Rotation.from_rotvec(viewing_angle * rotation_axis / np.linalg.norm(rotation_axis))
        nu_direction = -rot.apply(lv) # using the convention that nu_direction points to its origin
        zenith, azimuth = hp.cartesian_to_spherical(*nu_direction)
        return zenith, azimuth

    def minimizer(
            self, params, vertex_x, vertex_y, vertex_z, minimize = True, timing_k = False,
            first_iter = False, banana = False,  direction = [0, 0], ch_Vpol = 6, ch_Hpol = False,
            full_station = False, single_pulse =False, fixed_timing = False,
            starting_values = False, penalty = False, sim = False
        ):
        """

        Parameters
        ----------
        params: list
            input paramters for viewing angle / direction
        vertex_x, vertex_y, vertex_z: float
            input vertex
        minimize: Boolean
            If true, minimization output is given (chi2). If False, parameters are returned. Default minimize = True.
        first_iter: Boolean
            If true, raytracing is performed. If false, raytracing is not perfomred. Default first_iter = False.
        banana: Boolean
            If true, input values are viewing angle and energy. If false, input values should be theta and phi. Default banana = False.
        direction: list
            List with phi and theta direction. This is only for determining contours. Default direction = [0,0].
        ch_Vpol: int
            channel id for the Vpol of the reference pulse. Must be upper Vpol in phased array. Default ch_Vpol = 6.
        ch_Hpol: int
            channel id for the Hpol which is closest by the ch_Vpol
        full_station:
            if True, all raytype solutions for all channels are used, regardless of SNR of pulse. Default full_station = True.
        single_pulse: Boolean
            if True, only 1 pulse is used from the reference Vpol. Default single_pulse = False.
        fixed_timing: Boolean
            if True, the positions of the pulses using the simulated timing is used. This only works for the simulated vertex and for Alvarez2009 reconstruction and simulation. Default fixed_timing = False.
        starting_values: Boolean
            if True, the phased array cluster is used to obtain starting values for the viewing angle and the energy to limit the timing for the brute force approach. Default starting_values = False.
        penalty: Boolean
            if True, a penalty is included such that the reconstruction is not allowed to overshoot the traces with snr< 3.5. Default penalty = False.

        """

        model_sys = 0

        if banana: ## if input is viewing angle and energy, they need to be transformed to zenith and azimuth
            if len(params) ==3:
                cherenkov_angle, angle, log_energy = params
                # print("viewing angle and energy and angle ", [np.rad2deg(cherenkov_angle), log_energy, np.rad2deg(angle)])
            if len(params) == 2:
                cherenkov_angle, log_energy = params
                angle = self._angle
                print("viewing angle and energy and angle ", [np.rad2deg(cherenkov_angle), log_energy, np.rad2deg(angle)])
            if len(params) == 1:
                cherenkov_angle = self._viewing_angle
                self._pol_angle = params
                print("pol angle", self._pol_angle)
                log_energy = self._log_energy
                angle = self._angle
            energy = 10**log_energy

            zenith, azimuth = self._transform_angles(cherenkov_angle, angle)

            if np.rad2deg(zenith) > 120:
                return np.inf ## not in field of view
            # if np.rad2deg(zenith) < 20:  ## not in field of view
            #     return np.inf

        else:
            if len(params) ==3:
                zenith, azimuth, log_energy = params
                energy = 10**log_energy
            if len(params) == 1:
                log_energy = params

                energy = 10**log_energy[0]
                zenith, azimuth = direction

        azimuth = self.transform_azimuth(azimuth)

        pol_angle = 0
        if self._single_pulse_fit:
            pol_angle = self._pol_angle
        traces, timing, launch_vector, viewingangles, raytypes, pol = self._simulation.simulation(
            self._det, self._station, vertex_x, vertex_y, vertex_z, zenith, azimuth, energy,
            self._use_channels, first_iter = first_iter, starting_values = starting_values,
            pol_angle = pol_angle) ## get traces due to neutrino direction and vertex position
        chi2 = 0
        all_chi2 = dict()
        over_reconstructed = [] ## list for channel ids where reconstruction is larger than data
        extra_channel = 0 ## count number of pulses besides triggering pulse in Vpol + Hpol


        rec_traces = {} ## to store reconstructed traces
        data_traces = {} ## to store data traces
        data_timing = {} ## to store timing


        #get timing and pulse position for raytype of triggered pulse
        for iS in raytypes[ch_Vpol]:
            if sim or self._sim_vertex: raytype = ['direct', 'refracted', 'reflected'].index(self._station[stnp.raytype_sim]) + 1
            if not sim and not self._sim_vertex: raytype = ['direct', 'refracted', 'reflected'].index(self._station[stnp.raytype]) + 1

            if raytypes[ch_Vpol][iS] == raytype:
                solution_number = iS
        T_ref = timing[ch_Vpol][solution_number]
        trace_start_time_ref = self._station.get_channel(ch_Vpol).get_trace_start_time()

        if sim or self._sim_vertex: k_ref = self._station[stnp.pulse_position_sim]# get pulse position for triggered pulse
        if not sim and not self._sim_vertex:  k_ref = self._station[stnp.pulse_position]
        ks = {}

        ich = -1
        reduced_chi2_Vpol = 0
        reduced_chi2_Hpol = 0
        dict_dt = {}
        for ch in self._use_channels:
            dict_dt[ch] = {}

        ### 1. Set timings of fit windows
        for channel in self._station.iter_channels(): ### FIRST SET TIMINGS
            channel_id = channel.get_id()
            if (channel_id in self._use_channels):

                ich += 1 ## number of channel
                data_trace = np.copy(channel.get_trace())
                rec_traces[channel_id] = {}
                data_traces[channel_id] = {}
                data_timing[channel_id] = {}
                all_chi2[channel_id] = np.zeros(2)
                ### if no solution exist, than analytic voltage is zero
                rec_trace = np.zeros(len(data_trace))# if there is no raytracing solution, the trace is only zeros

                delta_k = [] ## if no solution type exist then channel is not included
                num = 0
                chi2s = np.zeros(2)
                for i_trace, key in enumerate(traces[channel_id]):#get dt for phased array pulse
                    rec_trace = traces[channel_id][key]

                    delta_T =  timing[channel_id][key] - T_ref
                    if (channel_id == ch_Vpol) & (key == solution_number):
                        trace_ref = i_trace

                    ## before correlating, set values around maximum voltage trace data to zero
                    delta_toffset = delta_T * self._sampling_rate
                    # take into account unequal trace start times
                    delta_toffset -= (channel.get_trace_start_time() - trace_start_time_ref) * self._sampling_rate

                    ### figuring out the time offset for specfic trace
                    dk = int(k_ref + delta_toffset )# where do we expect the pulse to be wrt channel 6 main pulse and rec vertex position

                    data_trace_timing = np.copy(data_trace) ## cut data around timing
                    ## DETERMIINE PULSE REGION DUE TO REFERENCE TIMING

                    data_timing_timing = channel.get_times()#np.arange(0, len(channel.get_trace()), 1)#

                    data_window = [30 * self._sampling_rate, 50 * self._sampling_rate] # window around pulse in samples
                    include_samples = np.arange(int(dk - data_window[0]), int(dk + data_window[1]))
                    first_sample = np.max([include_samples[0], 0]) # make sure the first index is non-negative
                    mask = (include_samples >= 0) & (include_samples < len(data_trace_timing))
                    data_timing_timing_1, data_trace_timing_1 = np.zeros((2,len(include_samples)))
                    if np.sum(mask):
                        data_timing_timing_1[mask] = data_timing_timing[first_sample:include_samples[-1] + 1]
                        data_trace_timing_1[mask] = data_trace_timing[first_sample:include_samples[-1] + 1]
                    data_timing_timing = data_timing_timing_1

                    corr = signal.correlate(rec_trace, data_trace_timing_1)
                    dt1 = np.argmax(corr) - (len(corr)/2) + 1

                    chi2_dt1 = np.sum((np.roll(rec_trace, math.ceil(-1*dt1)) - data_trace_timing_1)**2 / ((self._Vrms)**2))/len(rec_trace)
                    dt2 = np.argmax(corr) - (len(corr)/2)
                    chi2_dt2 = np.sum((np.roll(rec_trace, math.ceil(-1*dt2)) - data_trace_timing_1)**2 / ((self._Vrms)**2))/len(rec_trace)
                    if chi2_dt2 < chi2_dt1:
                        dt = dt2
                    else:
                        dt = dt1

                    dict_dt[channel_id][i_trace] = dt

                    #TODO - REMOVE (used for debugging)
                    # if self._ultradebug:
                    #     fig, axs = plt.subplots(2,1,)
                    #     fig.subplots_adjust(hspace=0)
                    #     axs[0].plot(np.roll(rec_trace, math.ceil(-dt)), color='g')
                    #     axs[0].plot(data_trace_timing_1, color='k')
                    #     axs[1].plot(corr)
                    #     axs[0].set_title(f'{channel_id} / {i_trace} / {dt:.1f} / {chi2_dt1:.2f}')
                    #     plt.show()

        # TODO - REMOVE!
        # logger.debug("time shifts (channel / trace / shift):")
        # for ch in dict_dt.keys():
        #     for i_trace in dict_dt[ch].keys():
        #         logger.debug(f'{ch} / {i_trace} / {dict_dt[ch][i_trace]}')

        if fixed_timing:
            for i_ch in self._use_channels:
                if 1:#i_ch not in self._PA_cluster_channels:
                    dict_dt[i_ch][0] = dict_dt[ch_Vpol][trace_ref]
                    dict_dt[i_ch][1] = dict_dt[ch_Vpol][trace_ref]

        ### 2. Perform fit #TODO - merge into above loop to reduce amount of code.
        dof = 0
        for channel in self._station.iter_channels():
            channel_id = channel.get_id()
            if channel_id in self._use_channels:
                chi2s = np.zeros(2)
                echannel = np.zeros(2)
                dof_channel = 0
                rec_traces[channel_id] = {}
                data_traces[channel_id] = {}
                data_timing[channel_id] = {}
                data_trace = np.copy(channel.get_trace())
                if traces[channel_id]:
                    for i_trace, key in enumerate(traces[channel_id]): ## iterate over ray type solutions
                        rec_trace = traces[channel_id][key]
                        delta_T =  timing[channel_id][key] - T_ref
                        ## before correlating, set values around maximum voltage trace data to zero
                        delta_toffset = delta_T * self._sampling_rate
                        # adjust for unequal trace start times
                        # if adjust_for_start_time:
                        delta_toffset -= (channel.get_trace_start_time() - trace_start_time_ref) * self._sampling_rate

                        ### figuring out the time offset for specfic trace
                        dk = int(k_ref + delta_toffset )
                        if 1:#
                            data_trace_timing = np.copy(data_trace) ## cut data around timing

                            ## DETERMINE PULSE REGION DUE TO REFERENCE TIMING
                            data_timing_timing = np.copy(channel.get_times())#np.arange(0, len(channel.get_trace()), 1)#
                            dk_1 = channel.get_trace_start_time() + dk / self._sampling_rate # this is defined also if we're outside the trace. Does introduce a rounding error?

                            data_timing_timing = data_timing_timing[int(dk - self._sampling_rate*30) : int(dk + self._sampling_rate*50)] ## 800 samples, like the simulation
                            data_trace_timing = data_trace_timing[int(dk - self._sampling_rate*30) : int(dk + self._sampling_rate*50)]

                            fixed_timing_PA_cluster = True
                            if fixed_timing_PA_cluster:
                                if channel_id in self._PA_cluster_channels:
                                    if i_trace == trace_ref:
                                        dict_dt[channel_id][trace_ref] = dict_dt[ch_Vpol][trace_ref]


                            dt = dict_dt[channel_id][i_trace]
                            rec_trace = np.roll(rec_trace, math.ceil(-1*dt))

                            #### select fitting time-window ####
                            if channel_id in self._Hpol_channels:
                                indices = [i for i, x in enumerate(data_timing_timing) if (x > (dk_1 + self._window_Hpol[0])  and (x < (dk_1 + self._window_Hpol[1]) ))]
                            else:
                                indices = [i for i, x in enumerate(data_timing_timing) if (x > (dk_1 + self._window_Vpol[0])  and (x < (dk_1 + self._window_Vpol[1]) ))]
                            if not len(indices):
                                # print("empty timing window for channel {}, RT solution {} - skipping...".format(channel_id, i_trace))
                                rec_traces[channel_id][i_trace] = np.zeros(int(80 * self._sampling_rate))
                                data_traces[channel_id][i_trace] = np.zeros(int(80 * self._sampling_rate))
                                data_timing[channel_id][i_trace] = np.zeros(int(80 * self._sampling_rate))
                                continue
                            rec_trace = rec_trace[indices]
                            data_trace_timing = data_trace_timing[indices]
                            data_timing_timing = data_timing_timing[indices]


                            ks[channel_id] = delta_k
                            rec_traces[channel_id][i_trace] = rec_trace
                            data_traces[channel_id][i_trace] = data_trace_timing
                            data_timing[channel_id][i_trace] = data_timing_timing

                            ### set vrms and time_window for channel
                            # we check the pulse SNR in the data window
                            # for channels other than the PA cluster,
                            # we only include channels with SNR > 3.5 (make this customizable?)
                            if channel_id in self._Hpol_channels:
                                Vrms = self._Vrms_Hpol
                            else:
                                Vrms = self._Vrms
                            if len(data_trace_timing):
                                SNR = abs(max(data_trace_timing) - min(data_trace_timing) ) / (2*Vrms)
                            else: # we are apparently outside the recorded trace
                                SNR = 0

                            if fixed_timing:
                                if SNR > 3.5:
                                    echannel[i_trace] = 1

                            # compute chi squared. We take the mean rather than the sum to avoid an unjustified preference
                            # for traces which are only partially contained in the data window
                            chi2s[i_trace] = np.mean((rec_trace - data_trace_timing)**2 / ((Vrms+model_sys*abs(data_trace_timing))**2))

                            if (single_pulse):
                                if ((channel_id == ch_Vpol) and (i_trace == trace_ref)):
                                    reduced_chi2_Vpol = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)
                                    Vpol_ref = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)
                                dof_channel += 1

                            elif (self._single_pulse_fit) and (i_trace == trace_ref): #use only 1 Vpol and 1 Hpol as input channels!
                                if ((channel_id == ch_Vpol) and (i_trace == trace_ref)):
                                    reduced_chi2_Vpol = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)
                                    Vpol_ref = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)
                                if ((channel_id == ch_Hpol) and (i_trace == trace_ref)):
                                    reduced_chi2_Hpol = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)
                                    Hpol_ref = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)
                                dof_channel += 1
                            elif ((channel_id in self._PA_channels) and (i_trace == trace_ref) and starting_values) and not self._single_pulse_fit: #PA_cluster_channels contains all channels that are definitely included in the fit and for which the timings are fixed.
                                if channel_id == ch_Vpol:
                                    reduced_chi2_Vpol = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)
                                    Vpol_ref = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)

                                dof_channel += 1
                                echannel[i_trace] = 1
                            elif ((channel_id in self._PA_cluster_channels) and (i_trace == trace_ref) and not starting_values and not self._single_pulse_fit):
                                if channel_id == ch_Vpol:
                                    reduced_chi2_Vpol = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)
                                    Vpol_ref = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)
                                if channel_id == ch_Hpol:
                                    reduced_chi2_Hpol = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms_Hpol)**2))/len(rec_trace)
                                    Hpol_ref = np.sum((rec_trace - data_trace_timing)**2 / ((self._Vrms+model_sys*abs(data_trace_timing))**2))/len(rec_trace)

                                dof_channel += 1
                                echannel[i_trace] = 1
                            elif ((channel_id in self._use_channels) and (full_station) and (SNR > 3.5) and not starting_values and not self._single_pulse_fit):
                                dof_channel += 1
                                echannel[i_trace] = 1
                            elif penalty:
                                if abs(max(rec_trace) - min(rec_trace))/(2*Vrms) > 4.0:
                                    chi2s[i_trace] = np.inf

                else:#if no raytracing solution exist
                    rec_traces[channel_id][0] = np.zeros(80 * int(self._sampling_rate))
                    data_traces[channel_id][0] = np.zeros(80 * int(self._sampling_rate))
                    data_timing[channel_id][0] = np.zeros(80 * int(self._sampling_rate))
                    rec_traces[channel_id][1] = np.zeros(80 * int(self._sampling_rate))
                    data_traces[channel_id][1] = np.zeros(80 * int(self._sampling_rate))
                    data_timing[channel_id][1] = np.zeros(80 * int(self._sampling_rate))

                #### if the pulses are overlapping, than we don't include them in the fit because the timing is not exactly known.
                if min([max(data_timing[channel_id][0]), max(data_timing[channel_id][1])]) > max([min(data_timing[channel_id][1]), min(data_timing[channel_id][0])]):
                    if int(min(data_timing[channel_id][1])) != 0:
    #
                        if (channel_id == ch_Vpol):
                            chi2 += chi2s[trace_ref]
                            all_chi2[channel_id][trace_ref] = chi2s[trace_ref]
                            dof += 1
                        if (channel_id == ch_Hpol):
                            if 'Hpol_ref' in locals(): #Hpol_ref is only defined when this is supposed to be included in the fit
                                chi2 += chi2s[trace_ref]
                                all_chi2[channel_id][trace_ref] = chi2s[trace_ref]

                else:
                    extra_channel += echannel[0]
                    extra_channel += echannel[1]
                    # chi2 += chi2s[0]
                    # chi2 += chi2s[1]
                    chi2 += np.sum(chi2s[np.where(echannel)])
                    dof += dof_channel
                    all_chi2[channel_id] = np.where(echannel, chi2s, 0)

        self.__dof = dof
        if timing_k:
            return ks
        if not minimize:
            return [rec_traces, data_traces, data_timing, all_chi2, [reduced_chi2_Vpol, reduced_chi2_Hpol], over_reconstructed, extra_channel]

        return chi2
        """
                ### helper functions for plotting
        def mollweide_azimuth(az):
            az -= (simulated_azimuth - np.deg2rad(180)) ## put simulated azimuth at 180 degrees
            az = np.remainder(az, np.deg2rad(360)) ## rotate values such that they are between 0 and 360
            az -= np.deg2rad(180)
            return az

        def mollweide_zenith(zen):
            zen -= (simulated_zenith  - np.deg2rad(90)) ## put simulated azimuth at 90 degrees
            zen = np.remainder(zen, np.deg2rad(180)) ## rotate values such that they are between 0 and 180
            zen -= np.deg2rad(90) ## hisft to mollweide projection
            return zen


        def get_normalized_angle(angle, degree=False, interval=np.deg2rad([0, 360])):
            import collections
            if degree:
                interval = np.rad2deg(interval)
            delta = interval[1] - interval[0]
            if(isinstance(angle, (collections.Sequence, np.ndarray))):
                angle[angle >= interval[1]] -= delta
                angle[angle < interval[0]] += delta
            else:
                while (angle >= interval[1]):
                    angle -= delta
                while (angle < interval[0]):
                    angle += delta
            return angle
        """
    def end(self):
        pass


def save_fig(fig, fname, format='.png'):
    """
    Save a matplotlib Figure instance

    Parameters
    ----------
    fig : matplotlib Fig instance
    fname : string
        location / name
    format : string | list (default: '.png')
        format(s) to save to save the figure to.
        If a list, save the figure to multiple formats.
        Can also include '.pickle'/'.pkl' to enable the Fig to be
        imported and edited in the future

    """
    formats = np.atleast_1d(format)
    for fmt in formats:
        if ('pickle' in fmt) or ('pkl' in fmt):
            with open(fname+'.pkl', 'wb') as file:
                pickle.dump(fig, file)
        else:
            if not fmt[0] == '.':
                fmt = '.' + fmt
            fig.savefig(fname+fmt)