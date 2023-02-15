import numpy as np
import streamlit as st
from NuRadioReco.detector.webinterface.utils.page_config import page_configuration
from NuRadioReco.detector.webinterface.utils.helper_display_station import build_station_selection, load_station_position_info, get_all_station_measurement_names, load_general_info, build_channel_selection, get_all_channel_measurements_names, load_channel_position_info, load_device_position_info, get_all_signal_chain_config_names, load_signal_chain_information, get_all_device_measurements_names
import pandas as pd
from datetime import datetime
from datetime import time

def build_main_page(cont):
    cont.title('Display station information')
    cont.header('select station')
    collection_name = 'station_rnog'
    # select the station which should be displayed
    selected_station_name, selected_station_id = build_station_selection(cont, collection_name)

    # makes sure the data is reloaded if collection or station is changed, otherwise the date stays in the cache
    if 'station_id' not in st.session_state:
        st.session_state['station_id'] = 0

    # get general station information

    cont.header('station information')
    # load the station general information
    @st.experimental_memo()
    def get_general_stat_info():
        station_info = load_general_info(selected_station_id)
        if 'station_comment' in station_info[selected_station_id].keys():
            db_comment = f'{station_info[selected_station_id]["station_comment"]}'
            if db_comment == '':
                db_comment = 'No comments'
        else:
            db_comment = 'No comments'

        c_time = station_info[selected_station_id]['commission_time']
        dc_time = station_info[selected_station_id]['decommission_time']

        channel_dict = {}
        if 'channels' in list(station_info[selected_station_id].keys()):
            channel_dict = station_info[selected_station_id]['channels']

        device_dic = {}
        if 'devices' in list(station_info[selected_station_id].keys()):
            device_dic = station_info[selected_station_id]['devices']

        return c_time, dc_time, db_comment, channel_dict, device_dic

    comm_time, decomm_time, comment, cha_dic, dev_dic = get_general_stat_info()

    # display the (de)commission time
    coll_comm_1, coll_comm_2 = cont.columns([1,1])
    coll_comm_1.markdown('**commission time**')
    coll_comm_1.code(f'{comm_time.date()} {comm_time.time().strftime("%H:%M:%S")}')
    coll_comm_2.markdown('**decommission time**')
    coll_comm_2.code(f'{decomm_time.date()} {decomm_time.time().strftime("%H:%M:%S")}')

    # display the comment
    cont.markdown('**comments:**')
    cont.text(comment)

    # get the station position

    cont.subheader('position info')
    coll_pos_select1, coll_pos_select2 = cont.columns([1, 1])
    selected_primary_time = coll_pos_select1.date_input('Primary time', value=datetime.utcnow(), help='If the selected time is before 2018/01/01, the entry will be interpreted as "None"')
    selected_primary_time = datetime.combine(selected_primary_time, time(12, 0, 0))
    if selected_primary_time < datetime(2018, 1, 1, 0, 0, 0):
        selected_primary_time = None
    measurement_names_db = list(get_all_station_measurement_names())
    measurement_names_db.insert(0, 'not specified')
    selected_measurement_name = coll_pos_select2.selectbox('Measurement name:', options=measurement_names_db)

    if 'measurement_name_key' not in st.session_state:
        st.session_state['measurement_name_key'] = ''

    if 'primary_time_key' not in st.session_state:
        st.session_state['primary_time_key'] = None

    if st.session_state.measurement_name_key != selected_measurement_name:
        st.session_state.measurement_name_key = selected_measurement_name
        st.experimental_memo.clear()
        st.experimental_rerun()

    if st.session_state.primary_time_key != selected_primary_time:
        st.session_state.primary_time_key = selected_primary_time
        st.experimental_memo.clear()
        st.experimental_rerun()

    # load the position information into the cache
    @st.experimental_memo
    def get_pos_info():
        position_info = load_station_position_info(station_id=selected_station_id, primary_time=selected_primary_time, measurement_name=selected_measurement_name)
        meas_name = None
        pri_times = [{'start': None, 'end': None}]
        pos = [None, None, None]
        if position_info != []:
            meas_name = position_info[0]["measurements"]["measurement_name"]
            pos = position_info[0]["measurements"]["position"]
            pri_times = position_info[0]["measurements"]["primary_measurement"]
        return {'name': meas_name, 'position': pos, 'primary': pri_times}

    pos_info = get_pos_info()

    cont.markdown('**measurement name**')
    cont.text(f'{pos_info["name"]}')
    cont.markdown('**primary times**')
    for times in pos_info['primary']:
        coll1_pri, coll2_pri = cont.columns([1,1])
        if times["start"] is None:
            coll1_pri.code(f'start: None')
            coll2_pri.code(f'end: None')
        else:
            coll1_pri.code(f'start: {times["start"].date()} {times["start"].time().strftime("%H:%M:%S")}')
            coll2_pri.code(f'end: {times["end"].date()} {times["end"].time().strftime("%H:%M:%S")}')

    cont.markdown('**position**')
    coll1, coll2, coll3 = cont.columns([1, 1, 1])
    coll1.code(f'x: {pos_info["position"][0]}')
    coll2.code(f'y: {pos_info["position"][1]}')
    coll3.code(f'z: {pos_info["position"][2]}')

    cont.header('channel information')

    # load and cache the channel information (is only loaded once)
    @st.experimental_memo
    def get_general_channel_info_table():
        if cha_dic != {}:
            # transform the channel data in a dataframe
            antenna_type = []
            antenna_VEL = []
            antenna_S11 = []
            commission_time = []
            decommission_time = []
            comments = []
            channel_ids = []
            for cha in cha_dic.keys():
                channel_ids.append(cha)
                antenna_type.append(cha_dic[cha]['ant_type'])
                antenna_VEL.append(cha_dic[cha]['ant_VEL'])
                antenna_S11.append(cha_dic[cha]['ant_S11'])
                commission_time.append(cha_dic[cha]['commission_time'].date())
                decommission_time.append(cha_dic[cha]['decommission_time'].date())
                if 'channel_comment' in cha_dic[cha].keys():
                    comments.append(cha_dic[cha]['channel_comment'])
                else:
                    comments.append('')
            df = pd.DataFrame({'id': channel_ids, 'antenna type': antenna_type, 'antenna VEL': antenna_VEL, 'antenna S11': antenna_S11, 'commission': commission_time, 'decommission': decommission_time, 'comment': comments})
        else:
            df = pd.DataFrame({'A': []})

        df = df.sort_values(by=['id'])

        return df

    general_channel_data = get_general_channel_info_table()

    def highlight_cols(s):
        color = 'yellow'
        return 'background-color: %s' % color

    cont.subheader('general information')
    cont.dataframe(general_channel_data.style.applymap(highlight_cols, subset=pd.IndexSlice[:, ['id']]), use_container_width=True)

    cont.subheader('position and rotation/orientation information')

    coll_pos_cha_select1, coll_pos_cha_select2 = cont.columns([1, 1])
    selected_primary_time_cha = coll_pos_cha_select1.date_input('Primary time', value=datetime.utcnow(), key='channel', help='If the selected time is before 2018/01/01, the entry will be interpreted as "None"')
    selected_primary_time_cha = datetime.combine(selected_primary_time_cha, time(12, 0, 0))
    if selected_primary_time_cha < datetime(2018, 1, 1, 0, 0, 0):
        selected_primary_time_cha = None
    measurement_names_cha_db = list(get_all_channel_measurements_names())
    measurement_names_cha_db.insert(0, 'not specified')
    selected_measurement_name_cha = coll_pos_cha_select2.selectbox('Measurement name:', options=measurement_names_cha_db, key='measurement_name_channel_pos')

    if 'channel_measurement_name_key' not in st.session_state:
        st.session_state['channel_measurement_name_key'] = ''

    if 'channel_primary_time_key' not in st.session_state:
        st.session_state['channel_primary_time_key'] = None

    if st.session_state.channel_measurement_name_key != selected_measurement_name_cha:
        st.session_state.channel_measurement_name_key = selected_measurement_name_cha
        st.experimental_memo.clear()
        st.experimental_rerun()

    if st.session_state.channel_primary_time_key != selected_primary_time_cha:
        st.session_state.channel_primary_time_key = selected_primary_time_cha
        st.experimental_memo.clear()
        st.experimental_rerun()

    # load and cache the channel information (is only loaded once)
    @st.experimental_memo
    def get_position_channel_info_table():
        cha_positions = load_channel_position_info(station_id=selected_station_id, primary_time=selected_primary_time_cha, measurement_name=selected_measurement_name_cha)
        if cha_positions != []:
            # transform the channel data in a dataframe
            channel_ids = []
            measurement_name = []
            curr_time_primary_start = []
            curr_time_primary_end = []
            other_primary_times = []
            position = []
            rotation = []
            orientation = []
            measurement_time = []
            for dic in cha_positions:
                other_primary_times_help = ''
                count_other_primary = 0
                for ipm, pm in enumerate(dic['measurements']['primary_measurement']):
                    pm_start = pm['start'].replace(microsecond=0)
                    pm_end = pm['end'].replace(microsecond=0)
                    if selected_primary_time_cha is None:
                        curr_time_primary_end.append(None)
                        curr_time_primary_start.append(None)
                        if count_other_primary > 0:
                            other_primary_times_help = other_primary_times_help + f', \n{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                        else:
                            other_primary_times_help = other_primary_times_help + f'{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                        count_other_primary += 1
                    else:
                        if pm_start <= selected_primary_time_cha and pm_end > selected_primary_time_cha:
                            curr_time_primary_start.append(pm_start)
                            curr_time_primary_end.append(pm_end)
                        else:
                            if count_other_primary > 0:
                                other_primary_times_help = other_primary_times_help + f', \n{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                            else:
                                other_primary_times_help = other_primary_times_help + f'{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                            count_other_primary += 1
                other_primary_times.append(other_primary_times_help)
                channel_ids.append(dic['measurements']['channel_id'])
                measurement_name.append(dic['measurements']['measurement_name'])
                measurement_time.append(dic['measurements']['measurement_time'])
                position.append(dic['measurements']['position'])
                rotation.append([float(dic['measurements']['rotation']['theta']), float(dic['measurements']['rotation']['phi'])])
                orientation.append([float(dic['measurements']['orientation']['theta']), float(dic['measurements']['orientation']['phi'])])

            df = pd.DataFrame({'id': channel_ids, 'measurement': measurement_name, 'measurement time': measurement_time, 'position (x,y,z)': position, 'rotation (theta, phi)': rotation, 'orientation (theta, phi)': orientation, 'primary: start': curr_time_primary_start, 'primary: end': curr_time_primary_end, 'other primary times': other_primary_times})
            df = df.sort_values(by=['id'])
        else:
            df = pd.DataFrame({'id': [None], 'measurement': [None], 'measurement time': [None], 'position (x,y,z)': [None], 'rotation (theta, phi)': [None], 'orientation (theta, phi)': [None], 'primary: start': [None], 'primary: end': [None], 'other primary times': [None]})
        return df

    channel_position_table = get_position_channel_info_table()

    cont.dataframe(channel_position_table.style.applymap(highlight_cols, subset=pd.IndexSlice[:, ['id']]), use_container_width=True)

    cont.subheader('signal chain information')

    coll_sig_cha_select1, coll_sig_cha_select2 = cont.columns([1, 1])
    selected_primary_time_sig = coll_sig_cha_select1.date_input('Primary time', value=datetime.utcnow(), key='signal', help='If the selected time is before 2018/01/01, the entry will be interpreted as "None"')
    selected_primary_time_sig = datetime.combine(selected_primary_time_sig, time(12, 0, 0))
    if selected_primary_time_sig < datetime(2018, 1, 1, 0, 0, 0):
        selected_primary_time_sig = None
    config_names_cha_db = list(get_all_signal_chain_config_names())
    config_names_cha_db.insert(0, 'built-in')
    config_names_cha_db.insert(0, 'not specified')
    selected_config_name_cha = coll_sig_cha_select2.selectbox('Configuration name:', options=config_names_cha_db, key='measurement_name_signal_chain')

    if 'signal_chain_name_key' not in st.session_state:
        st.session_state['signal_chain_name_key'] = ''

    if 'signal_chain_primary_time_key' not in st.session_state:
        st.session_state['signal_chain_primary_time_key'] = None

    if st.session_state.signal_chain_name_key != selected_config_name_cha:
        st.session_state.signal_chain_name_key = selected_config_name_cha
        st.experimental_memo.clear()
        st.experimental_rerun()

    if st.session_state.signal_chain_primary_time_key != selected_primary_time_sig:
        st.session_state.signal_chain_primary_time_key = selected_primary_time_sig
        st.experimental_memo.clear()
        st.experimental_rerun()

    # load and cache the channel information (is only loaded once)
    @st.experimental_memo
    def get_signal_chain_info_table():
        if selected_config_name_cha == 'built-in':
            components = []
            channel_ids = []
            config_name = []
            curr_time_primary_start = []
            curr_time_primary_end = []
            other_primary_times = []
            sig_chain_length = 0
            for cha_key in cha_dic:
                sig_chain = cha_dic[cha_key]['signal_ch']
                components.append(sig_chain)
                if len(sig_chain) > sig_chain_length:
                    sig_chain_length += len(sig_chain)
                channel_ids.append(cha_key)
                config_name.append('built-in')
                curr_time_primary_start.append(None)
                curr_time_primary_end.append(None)
                other_primary_times.append(None)

        else:
            signa_chain = load_signal_chain_information(station_id=selected_station_id, primary_time=selected_primary_time_sig, config_name=selected_config_name_cha)
            if signa_chain == []:
                return pd.DataFrame({'id': [None], 'configuration': [None], 'primary: start': [None], 'primary: end': [None], 'other primary times': [None]})

            # transform the channel data in a dataframe
            channel_ids = []
            config_name = []
            curr_time_primary_start = []
            curr_time_primary_end = []
            other_primary_times = []
            components = []
            sig_chain_length = 0
            for dic in signa_chain:
                other_primary_times_help = ''
                count_other_primary = 0
                for ipm, pm in enumerate(dic['measurements']['primary_measurement']):
                    pm_start = pm['start'].replace(microsecond=0)
                    pm_end = pm['end'].replace(microsecond=0)
                    if selected_primary_time_sig is None:
                        curr_time_primary_start.append(None)
                        curr_time_primary_end.append(None)
                        if count_other_primary > 0:
                            other_primary_times_help = other_primary_times_help + f', \n{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                        else:
                            other_primary_times_help = other_primary_times_help + f'{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                        count_other_primary += 1
                    else:
                        if pm_start <= selected_primary_time_sig and pm_end > selected_primary_time_sig:
                            curr_time_primary_start.append(pm_start)
                            curr_time_primary_end.append(pm_end)
                        else:
                            if count_other_primary > 0:
                                other_primary_times_help = other_primary_times_help + f', \n{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                            else:
                                other_primary_times_help = other_primary_times_help + f'{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                            count_other_primary += 1
                other_primary_times.append(other_primary_times_help)

                channel_ids.append(dic['measurements']['channel_id'])
                config_name.append(dic['measurements']['measurement_name'])
                sig_chain = dic['measurements']['sig_chain']
                if len(sig_chain) > sig_chain_length:
                    sig_chain_length += len(sig_chain)
                components.append(sig_chain)

        # sort the components
        comp_type1 = []
        comp_type2 = []
        comp_type3 = []
        comp_name1 = []
        comp_name2 = []
        comp_name3 = []
        comp_type4 = []
        comp_name4 = []
        if sig_chain_length == 1:
            for sig_dic in components:
                key = list(sig_dic.keys())[0]
                comp_type1.append(key)
                comp_name1.append(str(sig_dic[key]))
                print(comp_name1)
                print(comp_type1)
                print(channel_ids)
            df = pd.DataFrame({'id': channel_ids, 'configuration': config_name, 'comp type': comp_type1, 'comp name': comp_name1, 'primary: start': curr_time_primary_start, 'primary': curr_time_primary_end, 'other primary times': other_primary_times})
        elif sig_chain_length == 2:
            for sig_dic in components:
                key1 = list(sig_dic.keys())[0]
                key2 = list(sig_dic.keys())[1]
                comp_type1.append(key1)
                comp_name1.append(str(sig_dic[key1]))
                comp_type2.append(key2)
                comp_name2.append(str(sig_dic[key2]))
            df = pd.DataFrame({'id': channel_ids, 'configuration': config_name, 'comp type 1': comp_type1, 'comp name 1': comp_name1, 'comp type 2': comp_type2, 'comp name 2': comp_name2, 'primary: start': curr_time_primary_start, 'primary': curr_time_primary_end, 'other primary times': other_primary_times})
        elif sig_chain_length == 3:
            for sig_dic in components:
                key1 = list(sig_dic.keys())[0]
                key2 = list(sig_dic.keys())[1]
                if len(sig_dic) == 2:
                    comp_type1.append(key1)
                    comp_name1.append(str(sig_dic[key1]))
                    comp_type2.append(key2)
                    comp_name2.append(str(sig_dic[key2]))
                    comp_type3.append(None)
                    comp_name3.append(None)
                else:
                    key3 = list(sig_dic.keys())[2]
                    comp_type1.append(key1)
                    comp_name1.append(str(sig_dic[key1]))
                    comp_type2.append(key2)
                    comp_name2.append(str(sig_dic[key2]))
                    comp_type3.append(key3)
                    comp_name3.append(str(sig_dic[key3]))
            df = pd.DataFrame({'id': channel_ids, 'configuration': config_name, 'comp type 1': comp_type1, 'comp name 1': comp_name1, 'comp type 2': comp_type2, 'comp name 2': comp_name2, 'comp type 3': comp_type3, 'comp name 3': comp_name3, 'primary: start': curr_time_primary_start, 'primary': curr_time_primary_end, 'other primary times': other_primary_times})
        elif sig_chain_length == 4:
            for sig_dic in components:
                key1 = list(sig_dic.keys())[0]
                key2 = list(sig_dic.keys())[1]
                if len(sig_dic) == 2:
                    comp_type1.append(key1)
                    comp_name1.append(str(sig_dic[key1]))
                    comp_type2.append(key2)
                    comp_name2.append(str(sig_dic[key2]))
                    comp_type3.append(None)
                    comp_name3.append(None)
                    comp_type4.append(None)
                    comp_name4.append(None)
                elif len(sig_dic.keys()) == 3:
                    key3 = list(sig_dic.keys())[2]
                    comp_type1.append(key1)
                    comp_name1.append(str(sig_dic[key1]))
                    comp_type2.append(key2)
                    comp_name2.append(str(sig_dic[key2]))
                    comp_type3.append(key3)
                    comp_name3.append(str(sig_dic[key3]))
                    comp_type4.append(None)
                    comp_name4.append(None)
                else:
                    key3 = list(sig_dic.keys())[2]
                    key4 = list(sig_dic.keys())[3]
                    comp_type1.append(key1)
                    comp_name1.append(str(sig_dic[key1]))
                    comp_type2.append(key2)
                    comp_name2.append(str(sig_dic[key2]))
                    comp_type3.append(key3)
                    comp_name3.append(str(sig_dic[key3]))
                    comp_type4.append(key4)
                    comp_name4.append(str(sig_dic[key4]))

            df = pd.DataFrame({'id': channel_ids, 'configuration': config_name, 'comp type 1': comp_type1, 'comp name 1': comp_name1, 'comp type 2': comp_type2, 'comp name 2': comp_name2, 'comp type 3': comp_type3, 'comp name 3': comp_name3, 'comp type 4': comp_type4, 'comp name 4': comp_name4, 'primary: start': curr_time_primary_start, 'primary': curr_time_primary_end, 'other primary times': other_primary_times})
        else:
            df = pd.DataFrame({'id': [None], 'configuration': [None], 'primary: start': [None], 'primary: end': [None], 'other primary times': [None]})
        df = df.sort_values(by=['id'])

        return df

    signal_chain_table = get_signal_chain_info_table()

    cont.dataframe(signal_chain_table.style.applymap(highlight_cols, subset=pd.IndexSlice[:, ['id']]), use_container_width=True)

    cont.header('device information')

    @st.experimental_memo
    def get_general_device_info_table():
        if dev_dic != {}:
            # transform the device data in a dataframe
            device_name = []
            amplifier_name = []
            commission_time = []
            decommission_time = []
            comments = []
            device_ids = []
            for dev in dev_dic.keys():
                device_ids.append(dev)
                device_name.append(dev_dic[dev]['device_name'])
                amplifier_name.append(dev_dic[dev]['amp_name'])
                commission_time.append(dev_dic[dev]['commission_time'].date())
                decommission_time.append(dev_dic[dev]['decommission_time'].date())
                if 'device_comment' in dev_dic[dev].keys():
                    comments.append(dev_dic[dev]['device_comment'])
                else:
                    comments.append('')
            df = pd.DataFrame({'id': device_ids, 'device name': device_name, 'amplifier name': amplifier_name, 'commission': commission_time, 'decommission': decommission_time, 'comment': comments})
        else:
            df = pd.DataFrame({'id': None, 'device name': None, 'amplifier name': None, 'commission': None, 'decommission': None, 'comment': None})

        df = df.sort_values(by=['id'])

        return df

    general_device_data = get_general_device_info_table()

    cont.subheader('general information')
    cont.dataframe(general_device_data.style.applymap(highlight_cols, subset=pd.IndexSlice[:, ['id']]), use_container_width=True)

    cont.subheader('position and rotation/orientation information')

    coll_pos_dev_select1, coll_pos_dev_select2 = cont.columns([1, 1])
    selected_primary_time_dev = coll_pos_dev_select1.date_input('Primary time', value=datetime.utcnow(), key='dev_primary', help='If the selected time is before 2018/01/01, the entry will be interpreted as "None"')
    selected_primary_time_dev = datetime.combine(selected_primary_time_dev, time(12, 0, 0))
    if selected_primary_time_dev < datetime(2018, 1, 1, 0, 0, 0):
        selected_primary_time_dev = None
    measurement_names_dev_db = list(get_all_device_measurements_names())
    measurement_names_dev_db.insert(0, 'not specified')
    selected_measurement_name_dev = coll_pos_dev_select2.selectbox('Measurement name:', options=measurement_names_dev_db, key='measurement_name_device_pos')

    if 'device_measurement_name_key' not in st.session_state:
        st.session_state['device_measurement_name_key'] = ''

    if 'device_primary_time_key' not in st.session_state:
        st.session_state['device_primary_time_key'] = None

    if st.session_state.device_measurement_name_key != selected_measurement_name_dev:
        st.session_state.device_measurement_name_key = selected_measurement_name_dev
        st.experimental_memo.clear()
        st.experimental_rerun()

    if st.session_state.device_primary_time_key != selected_primary_time_dev:
        st.session_state.device_primary_time_key = selected_primary_time_dev
        st.experimental_memo.clear()
        st.experimental_rerun()

    # load and cache the channel information (is only loaded once)
    @st.experimental_memo
    def get_position_device_info_table():
        dev_positions = load_device_position_info(station_id=selected_station_id, primary_time=selected_primary_time_dev, measurement_name=selected_measurement_name_dev)
        if dev_positions != []:
            # transform the channel data in a dataframe
            device_ids = []
            measurement_name = []
            curr_time_primary_start = []
            curr_time_primary_end = []
            other_primary_times = []
            position = []
            rotation = []
            orientation = []
            measurement_time = []
            for dic in dev_positions:
                other_primary_times_help = ''
                count_other_primary = 0
                for ipm, pm in enumerate(dic['measurements']['primary_measurement']):
                    pm_start = pm['start'].replace(microsecond=0)
                    pm_end = pm['end'].replace(microsecond=0)
                    if selected_primary_time_dev is None:
                        curr_time_primary_end.append(None)
                        curr_time_primary_start.append(None)
                        if count_other_primary > 0:
                            other_primary_times_help = other_primary_times_help + f', \n{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                        else:
                            other_primary_times_help = other_primary_times_help + f'{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                        count_other_primary += 1
                    else:
                        if pm_start <= selected_primary_time_dev and pm_end > selected_primary_time_dev:
                            curr_time_primary_start.append(pm_start)
                            curr_time_primary_end.append(pm_end)
                        else:
                            if count_other_primary > 0:
                                other_primary_times_help = other_primary_times_help + f', \n{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                            else:
                                other_primary_times_help = other_primary_times_help + f'{pm_start.strftime("%Y/%m/%d %H:%M:%S")} - {pm_end.strftime("%Y/%m/%d %H:%M:%S")}'
                            count_other_primary += 1
                other_primary_times.append(other_primary_times_help)
                device_ids.append(dic['measurements']['device_id'])
                measurement_name.append(dic['measurements']['measurement_name'])
                measurement_time.append(dic['measurements']['measurement_time'])
                if len(dic['measurements']['position']) == 3:
                    position.append([dic['measurements']['position']])
                else:
                    position.append(dic['measurements']['position'])

                if dic['measurements']['rotation'] is None or dic['measurements']['orientation'] is None:
                    rotation.append([None, None])
                    orientation.append([None, None])
                else:
                    rotation.append([float(dic['measurements']['rotation']['theta']), float(dic['measurements']['rotation']['phi'])])
                    orientation.append([float(dic['measurements']['orientation']['theta']), float(dic['measurements']['orientation']['phi'])])

            df = pd.DataFrame({'id': device_ids, 'measurement': measurement_name, 'measurement time': measurement_time, 'position (x,y,z)': position, 'rotation (theta, phi)': rotation,
                               'orientation (theta, phi)': orientation, 'primary: start': curr_time_primary_start, 'primary: end': curr_time_primary_end, 'other primary times': other_primary_times})
            df = df.sort_values(by=['id'])
        else:
            df = pd.DataFrame(
                {'id': [None], 'measurement': [None], 'measurement time': [None], 'position (x,y,z)': [None], 'rotation (theta, phi)': [None], 'orientation (theta, phi)': [None], 'primary: start': [None],
                 'primary: end': [None], 'other primary times': [None]})
        return df

    device_position_table = get_position_device_info_table()

    cont.dataframe(device_position_table.style.applymap(highlight_cols, subset=pd.IndexSlice[:, ['id']]), use_container_width=True)

    if st.session_state.station_id != selected_station_id:
        st.session_state.station_id = selected_station_id
        st.experimental_memo.clear()
        st.experimental_rerun()
# main page setup
page_configuration()

main_cont = st.container()
build_main_page(main_cont)

