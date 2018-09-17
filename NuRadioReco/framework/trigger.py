from __future__ import absolute_import, division, print_function
try:
    import cPickle as pickle
except ImportError:
    import pickle

def deserialize(triggers_pkl):
    triggers = {}
    for data_pkl in triggers_pkl:
        trigger_type = pickle.loads(data_pkl)['_trigger_type']
        if(trigger_type == 'default'):
            trigger = Trigger(None)
            trigger.deserialize(data_pkl)
        elif(trigger_type == 'simple_threshold'):
            trigger = SimpleThresholdTrigger(None, None)
            trigger.deserialize(data_pkl)
        elif(trigger_type == 'high_low'):
            trigger = HighLowTrigger(None, None, None, None, None)
            trigger.deserialize(data_pkl)
        else:
            raise ValueError("unknown trigger type")
        triggers[trigger.get_name()] = trigger
    return triggers

class Trigger:
    """
    base class to store different triggers
    """

    def __init__(self, name, channels=None, trigger_type='default'):
        """
        initialize trigger class

        Parameters 
        -----------
        name: string
            unique name of the trigger
        channels: array of ints
            the channels that are involved in the trigger
        type: string
            the trigger type
        """
        self._name = name
        self._channels = channels
        self._triggered = False
        self._trigger_time = None
        self._trigger_type = trigger_type

    def has_triggered(self):
        """
        returns true if station has trigger, false otherwise
        """
        return self._triggered

    def set_triggered(self, triggered=True):
        """ set the trigger to True or False """
        self._triggered = triggered

    def set_trigger_time(self, time):
        """ set the trigger time

        Parameters 
        ----------
        time: float
            the trigger time in ns from the beginning of the trace
        """
        self._trigger_time = time

    def get_trigger_time(self):
        """
        get the trigger time (time with respect to beginning of trace)
        """
        return self._trigger_time
    
    def get_name(self):
        """ get trigger name """
        return self._name
    
    def get_type(self):
        """ get trigger type """
        return self._type
    
    def serialize(self):
        return pickle.dumps(self.__dict__, protocol=2)
    
    def deserialize(self, data_pkl):
        for key, value in pickle.loads(data_pkl).iteritems():
            setattr(self, key, value)

    def __str__(self):
        output = ""
        for key, value in self.__dict__.iteritems():
            output +="{}: {}\n".format(key[1:], value)
        return output
    
    def get_trigger_settings(self):
        output = {}
        for key, value in self.__dict__.iteritems():
            output[key[1:]] = value
        return output


class SimpleThresholdTrigger(Trigger):

    def __init__(self, name, threshold, channels=None, number_of_coincidences=1):
        """
        initialize trigger class

        Parameters 
        -----------
        name: string
            unique name of the trigger 
        threshold: float
            the threshold
        channels: array of ints or None
            the channels that are involved in the trigger
            default: None, i.e. all channels
        number_of_coincidences: int
            the number of channels that need to fulfill the trigger condition
            default: 1
        """
        Trigger.__init__(self, name, channels, 'simple_threshold')
        self._threshold = threshold
        self._number_of_coincidences = number_of_coincidences


class HighLowTrigger(Trigger):

    def __init__(self, name, threshold_high, threshold_low, high_low_window,
                 channel_coincidence_window, channels=None, number_of_coincidences=1):
        """
        initialize trigger class

        Parameters 
        -----------
        name: string
            unique name of the trigger 
        threshold_high: float
            the high threshold
        threshold_low: float
            the low threshold
        high_low_window: float
            the coincidence time between a high and low per channel
        channel_coincidence_window: float
            the coincidence time between triggers of different channels
        channels: array of ints or None
            the channels that are involved in the trigger
            default: None, i.e. all channels
        number_of_coincidences: int
            the number of channels that need to fulfill the trigger condition
            default: 1
        """
        Trigger.__init__(self, name, channels, 'high_low')
        self._number_of_coincidences = number_of_coincidences
        self._threshold_high = threshold_high
        self._threshold_low = threshold_low
        self._high_low_window = high_low_window
        self._coinc_window = channel_coincidence_window



class IntegratedPowerTrigger(Trigger):

    def __init__(self, name, threshold, channel_coincidence_window, channels=None, number_of_coincidences=1,
                 power_mean=None, power_std=None):
        """
        initialize trigger class

        Parameters 
        -----------
        name: string
            unique name of the trigger 
        threshold: float
            the threshold
        channel_coincidence_window: float
            the coincidence time between triggers of different channels
        channels: array of ints or None
            the channels that are involved in the trigger
            default: None, i.e. all channels
        number_of_coincidences: int
            the number of channels that need to fulfill the trigger condition
            default: 1
        """
        Trigger.__init__(self, name, channels, 'int_power')
        self._number_of_coincidences = number_of_coincidences
        self._threshold = threshold
        self._coinc_window = channel_coincidence_window
        self._power_mean = power_mean
        self._power_std = power_std
