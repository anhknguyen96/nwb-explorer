import collections

import numpy as np
from pynwb import TimeSeries, NWBHDF5IO, ProcessingModule
from pynwb.core import NWBDataInterface
from pynwb.image import ImageSeries

NWB_ROOT_NAME = 'root'


class NWBReader:
    nwb_map_id_api = {'acquisition': 'acquisition',
                      'analysis': 'analysis',
                      'epochs': 'epochs',
                      'processing': 'modules',  # this dictionary is needed mainly because of this
                      'stimulus': 'stimulus',
                      }

    @staticmethod
    def get_plottable_timeseries(time_series, resampling_size=None):
        data_size = time_series.data.size
        step = data_size // resampling_size if (resampling_size and data_size > resampling_size) else 1

        if time_series.timestamps:
            timestamps = time_series.timestamps
            timestamps = timestamps[::step].astype(float).tolist()
        else:

            timestamps = (time_series.rate * step) * np.arange(0, data_size // step) + time_series.starting_time
            timestamps = timestamps.tolist()
            # raise NotImplementedError('Still implicit timestamps are not supported')  # TODO
            # FIXME from pynwb documentation: Alternatively (i.e. when timestamps are not given), if your recordings are sampled at a uniform rate, you can supply starting_time and rate.

        # TODO we may need to rearrange that when dealing with spatial series: a different type of plot (3D or else) may me more adequate than what we're doing (i.e. splitting in multiple mono dimensional timeseries)
        time_series_array = NWBReader.get_mono_dimensional_timeseries_aux(time_series.data[::step])

        if len(time_series_array[0]) != len(timestamps):
            raise ValueError("Length of time series ({}) is different from timestamps ({}): "
                             .format(len(time_series_array[0]), len(timestamps)))
        return timestamps, time_series_array

    @staticmethod
    def get_timeseries_image_array(time_series):
        assert isinstance(time_series, ImageSeries)
        return NWBReader.get_raw_data(time_series.data)

    @staticmethod
    def get_raw_data(image_series_data):
        """Given a image_series data object returns a NumPy array with the raw data."""
        arr = np.zeros(image_series_data.shape, dtype=image_series_data.dtype)
        image_series_data.read_direct(arr)
        return arr

    @staticmethod
    def get_mono_dimensional_timeseries_aux(values):
        """Given a timeseries data object returns all mono dimensional timeserieses presents on it."""
        assert isinstance(values, np.ndarray), "This function is supposed to work with numpy array data"
        # Convert NaN to zeros FIXME if using data for anything else than plotting
        mono_time_series_list = np.nan_to_num(values.transpose(), copy=False).astype(float, copy=False).tolist()
        if len(values.shape) == 1:
            mono_time_series_list = [mono_time_series_list]
        return mono_time_series_list

    @staticmethod
    def get_all_parents(element):
        parents = []
        while hasattr(element, 'parent'):
            if (not element) or element.name == NWB_ROOT_NAME:
                break
            parents.insert(0, element)
            element = element.parent

        parentsnames = [p.name for p in parents]
        if isinstance(parents[0], ProcessingModule):
            parentsnames.insert(0, 'processing')
        return parents

    @staticmethod
    def find_from_key_recursive(dict_or_nwbobj, obj_to_find, parents=()):
        if dict_or_nwbobj is not None and not isinstance(dict_or_nwbobj, dict):
            if hasattr(dict_or_nwbobj, 'data_interfaces'):
                return NWBReader.find_from_key_recursive(dict_or_nwbobj.data_interfaces, obj_to_find, parents)
            if hasattr(dict_or_nwbobj, 'fields'):
                return NWBReader.find_from_key_recursive(dict_or_nwbobj.fields, obj_to_find, parents)

        if not isinstance(dict_or_nwbobj, dict):
            return None
        if obj_to_find.name in dict_or_nwbobj:
            if(dict_or_nwbobj[obj_to_find.name] == obj_to_find):
                return parents

        for k, v in dict_or_nwbobj.items():
            allparents = NWBReader.find_from_key_recursive(v, obj_to_find, parents + (k,))
            if allparents is not None:
                return allparents
        return None

    @staticmethod
    def get_timeseries_dimensions(time_series):
        return 1 if len(time_series.data.shape) == 1 else time_series.data.shape[0]

    def __init__(self, nwbfile_or_path):
        if isinstance(nwbfile_or_path, str):
            try:
                io = NWBHDF5IO(nwbfile_or_path, 'r')
                nwbfile = io.read()
            except Exception  as e:
                raise ValueError('Error reading the NWB file.', e.args)
        else:
            nwbfile = nwbfile_or_path
        self.nwbfile = nwbfile
        self.__data_interfaces = None
        self.__time_series_list = None

    def get_data_interfaces(self):
        if not self.__data_interfaces:
            self.__data_interfaces = self._get_data_interfaces(self.nwbfile)
        return self.__data_interfaces

    def _get_data_interfaces(self, node):
        """Given a NWBHDF5IO returns all the data_interfaces objects presents on it."""
        data_interfaces_list = []
        for child in node.children:
            if isinstance(child, NWBDataInterface):
                data_interfaces_list.append(child)
            data_interfaces_list += self._get_data_interfaces(child)
        return data_interfaces_list

    def _get_timeseries(self):
        """Given all the nwb_data_interfaces returns all of those that are timeseries objects."""
        time_series_list = []
        for data_interface in self.get_data_interfaces():
            if isinstance(data_interface, TimeSeries):
                time_series_list.append(data_interface)
        return time_series_list

    def get_all_timeseries(self):
        if not self.__time_series_list:
            self.__time_series_list = self._get_timeseries()
        return self.__time_series_list

    def extract_time_series_path(self, time_series):

        # This seems a little too custom but not seems to exist an obvious way to traverse the file hierarchically
        path = NWBReader.find_from_key_recursive(self.nwbfile.fields, time_series)

        return path

    def get_nwbfile(self):
        return self.nwbfile

    # Assuming requirements are NWBDataInterfaces provided by the API and NWB specification
    # http://pynwb.readthedocs.io/en/latest/overview_nwbfile.html#processing-modules
    def has_all_requirements(self, requirements):
        """Given a list of requirements verifies if all are meet ."""
        return all(self._check_requirement(requirement) for requirement in requirements)

    def _check_requirement(self, requirement):
        list_string = requirement.split('.')
        return self._check_requirement_full_path(list_string) if len(
            list_string) > 1 else self._check_requirement_data_interfaces(requirement)

    def _check_requirement_full_path(self, path_list):
        """Given a full_path requirement gets the initial group and expands it blindly in search of the last path
        element """
        group = NWBReader.nwb_map_id_api.get(path_list[0])
        if group is not None:
            nodes = [getattr(self.nwbfile, group)]
            for index, remaining_path in enumerate(path_list[1:]):
                for node in nodes:
                    if index == len(path_list) - 2:
                        if isinstance(node, dict):
                            for value in list(node.values()):
                                if value.neurodata_type == remaining_path:
                                    return True
                        else:
                            for child in node.children:
                                if child.neurodata_type == remaining_path:
                                    return True
                    else:
                        nodes = list(node.values()) if isinstance(node, dict) else node.children
        return False

    def _check_requirement_data_interfaces(self, requirement):
        """Given a requirement looks for a match in all the nwb_data_interfaces of the nwb file """
        for data_interfaces in self.get_data_interfaces():
            if data_interfaces.neurodata_type == requirement:
                return True
        return False



