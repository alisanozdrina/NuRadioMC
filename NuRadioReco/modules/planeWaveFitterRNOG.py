from NuRadioReco.utilities import geometryUtilities as geo_utl
import scipy.optimize as opt
import numpy as np
from radiotools import helper as hp
from NuRadioReco.framework.parameters import stationParameters as stnp
from NuRadioMC.utilities import medium
from NuRadioMC.SignalProp import propagation
from NuRadioReco.framework.parameters import showerParameters as shp
import matplotlib.pyplot as plt
from NuRadioReco.utilities import units, fft
import scipy.signal

class planeWaveFitterRNOG:
    " Fits the direction using plane wave fit to channels "
    
    def __init__(self):

        pass
        
        
    def begin(self, det, channel_ids = [0, 3, 9, 10], template = None):
        self.__channel_ids = channel_ids
        pass


    def run(self, evt, station, det, n_index = None, template = None, event_id = None, debug = True):
        if station.has_sim_station():
            ice = medium.get_ice_model('greenland_simple')
            prop = propagation.get_propagation_module('analytic')
            # determine signal arrival direction from stimulations
            for channel in station.get_sim_station().iter_channels():
                if channel.get_id() in self.__channel_ids:
                    print("channel id", channel.get_id())
                    shower_id = channel.get_shower_id() 
                    x2 = det.get_relative_position(station.get_id(), channel.get_id()) + det.get_absolute_position(station.get_id())
                    r = prop( ice, 'GL1')
                    r.set_start_and_end_point(evt.get_sim_shower(shower_id)[shp.vertex], x2)

                    r.find_solutions()
                    if(not r.has_solution()):
                        print("warning: no solutions")
                        continue
                    else:
                        for iS in range(r.get_number_of_solutions()):
                            solution_type = r.get_solution_type(iS)
                            print("solution type", solution_type)
                            if iS:#
                                signal_zenith = hp.cartesian_to_spherical(*r.get_receive_vector(iS))[0]
                                signal_azimuth = hp.cartesian_to_spherical(*r.get_receive_vector(iS))[1] 
                                print("solution type {}, signal_zenith {}, signal_azimuth {}".format(solution_type, np.rad2deg(signal_zenith), np.rad2deg(signal_azimuth)))
                            if not iS:#
                                signal_zenith1 = hp.cartesian_to_spherical(*r.get_receive_vector(iS))[0]
                                signal_azimuth1 = hp.cartesian_to_spherical(*r.get_receive_vector(iS))[1]
                                print("solution type {}, signal_zenith {}, signal_azimuth {}".format(solution_type, np.rad2deg(signal_zenith1), np.rad2deg(signal_azimuth1)))
            vertex = evt.get_sim_shower(shower_id)[shp.vertex]


        print("channels used for this reconstruction:", self.__channel_ids)


        self.__channel_pairs = []
        self.__relative_positions = []
        station_id = station.get_id() 
        for i in range(len(self.__channel_ids) - 1):
            for j in range(i + 1, len(self.__channel_ids)):
                relative_positions = det.get_relative_position(station_id, self.__channel_ids[i]) - det.get_relative_position(station_id, self.__channel_ids[j])
                self.__relative_positions.append(relative_positions)
                
                self.__channel_pairs.append([self.__channel_ids[i], self.__channel_ids[j]])
                
       
        self.__sampling_rate = station.get_channel(0).get_sampling_rate()
        self.__template = template
    
        if debug:
            fig, ax = plt.subplots( len(self.__channel_pairs), 2)

    
        def likelihood(angles, sim = False, rec = False):#, debug = False):#, station):
            zenith, azimuth = angles
            corr = 0
        
            for ich, ch_pair in enumerate(self.__channel_pairs):
                positions = self.__relative_positions[ich]
                times = []
                
                tmp = geo_utl.get_time_delay_from_direction(zenith, azimuth, positions, n=n_index)#,
       
                n_samples = -1*tmp * self.__sampling_rate
        
                pos = int(len(self.__correlation[ich]) / 2 - n_samples)
      
                corr += self.__correlation[ich, pos]
                
                if sim:
                    ax[ ich, 0].plot(self.__correlation[ich])
           
                    ax[ich, 0].axvline(pos, color = 'green', lw = 1, label = 'sim')#self.__correlation[ich, pos])
                    ax[ich,0].legend()
                    #ax[ich, 0].set_title("channel pair {}- {}".format( ch_pair[0], ch_pair[1]))
                if rec:
                    ax[ ich, 0].plot(self.__correlation[ich])
                    ax[ich, 0].set_ylim((0, max(self.__correlation[ich])))
     
                    ax[ich, 1].plot(station.get_channel(ch_pair[0]).get_times(), station.get_channel(ch_pair[0]).get_trace())
                  #  print("plot cannels", ch_pair)
                    ax[ich, 1].plot(station.get_channel(ch_pair[1]).get_times(), station.get_channel(ch_pair[1]).get_trace())
                    ax[ich, 1].set_xlabel("timing [ns]")
                    #ax[ich, 1].set_title("channel pair {}- {}".format( ch_pair[0], ch_pair[1]))
            if rec:
                fig.tight_layout()
                fig.savefig("/lustre/fs22/group/radio/plaisier/software/simulations/planeWaveFit/plots/corr_signal_{}.pdf".format(event_id)) 
           # print(stop)
            ### calculate timing shift due to plane wave
            ### get value in correlation due to timing
            
            
            likelihood = corr
           # print("likelihood", likelihood)
            return -1*likelihood
            
            

        trace = np.copy(station.get_channel(self.__channel_pairs[0][0]).get_trace())
        if self.__template is None:
            self.__correlation = np.zeros((len(self.__channel_pairs), len(np.abs(scipy.signal.correlate(trace, trace))) ))       

        else:
         
            self.__correlation = np.zeros((len(self.__channel_pairs), len(hp.get_normalized_xcorr(trace, self.__template))) )   
        #if not self.__template: self.__correlation = np.zeros((len(self.__channel_pairs), len(np.abs(scipy.signal.correlate(trace, trace))) ))
        for ich, ch_pair in enumerate(self.__channel_pairs):
           # print("self.__channel_pairs[0]", self.__channel_pairs[ich][0])                
            trace1 = np.copy(station.get_channel(self.__channel_pairs[ich][0]).get_trace())
            #print("channel", station.get_channel(4).get_trace())
            trace2 =np.copy(station.get_channel(self.__channel_pairs[ich][1]).get_trace())

            if self.__template is not None:
        #        self.__correlation = np.zeros((len(self.__channel_pairs), len(hp.get_normalized_xcorr(trace, self.__template))) )

                corr_1 = hp.get_normalized_xcorr(trace1, self.__template)
                #print("corr 1", corr_1)
                corr_2 = hp.get_normalized_xcorr(trace2, self.__template)
                #print("len corr1", len(corr_1))
               # print("corr 2", corr_2)
                #print(stop)
                #print("len channel pairs", len(self.__channel_pairs))
               # self.__correlation = np.zeros((len(self.__channel_pairs), len(corr_1)))
                sample_shifts = np.arange(-len(corr_1) // 2, len(corr_1) // 2, dtype=int)
                for i_shift, shift_sample in enumerate(sample_shifts):
                  #  print("corr 2", corr_2)
                    if (np.isnan(corr_2).any()):# or (not corr_2): ### with noise this should not be needed
                        self.__correlation[ich, i_shift] = 0#np.zeros(len(corr_2))
                    #    print("self correlation",np.zeros(len(corr_2)))
                    elif (np.isnan(corr_1).any()):
                        self.__correlation[ich, i_shift] = 0#np.zeros(len(corr_2))

                    else:
                        self.__correlation[ich, i_shift] = np.max(corr_1 * np.roll(corr_2, shift_sample))
            else:
                t_max1 = station.get_channel(self.__channel_pairs[ich][0]).get_times()[np.argmax(np.abs(trace1))]
                t_max2 = station.get_channel(self.__channel_pairs[ich][1]).get_times()[np.argmax(np.abs(trace2))]
                corr_range = 50 * units.ns
                snr1 = np.max(np.abs(station.get_channel(self.__channel_pairs[ich][0]).get_trace()))
                snr2 = np.max(np.abs(station.get_channel(self.__channel_pairs[ich][1]).get_trace()))
                if snr1 > snr2:
                    trace1[np.abs(station.get_channel(self.__channel_pairs[ich][0]).get_times() - t_max1) > corr_range] = 0
                else:
                    trace2[np.abs(station.get_channel(self.__channel_pairs[ich][1]).get_times() - t_max2) > corr_range] = 0
                self.__correlation[ich] = np.abs(scipy.signal.correlate(trace1, trace2))
          
            
        ### minimizer
        zen_start = np.deg2rad(0)
        zen_end = np.deg2rad(90)
        az_start = np.deg2rad(-180)
        az_end = np.deg2rad(180)

        if debug: print("Likelihood simulation", likelihood([signal_zenith, signal_azimuth], sim = True))
  
        ll = opt.brute(likelihood, ranges=(slice(zen_start, zen_end, 0.01), slice(az_start, az_end, 0.01)), finish = opt.fmin)
        


        rec_zenith = ll[0]
        rec_azimuth = ll[1]
        
        ##### run with reconstructed values
        if debug: print("likelihood reconstruction", likelihood(ll, rec = True))
        print("simulated zenith {} and reconstructed zenith {}".format(np.rad2deg(signal_zenith), np.rad2deg(rec_zenith)))
        print("simulated azimuth {} and reconstructed azimuth {}".format(np.rad2deg(signal_azimuth), np.rad2deg(rec_azimuth)))

        station[stnp.nu_zenith] = signal_zenith
        station[stnp.nu_azimuth] = signal_azimuth


    def end(self):
        pass
        
        
        
        