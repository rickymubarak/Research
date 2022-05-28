
import numpy as np
import pandas as pd
from pyFTS.common import FuzzySet, FLR, fts, flrg
from pyFTS.models import hofts
from pyFTS.models.multivariate import mvfts, grid, common
from types import LambdaType


class ClusteredMVFTS(mvfts.MVFTS):
    """
    Meta model for high order, clustered multivariate FTS
    """
    def __init__(self, **kwargs):
        super(ClusteredMVFTS, self).__init__(**kwargs)

        self.fts_method = kwargs.get('fts_method', hofts.WeightedHighOrderFTS)
        """The FTS method to be called when a new model is build"""
        self.fts_params = kwargs.get('fts_params', {})
        """The FTS method specific parameters"""
        self.model = None
        """The most recent trained model"""
        self.knn = kwargs.get('knn', 2)

        self.is_high_order = True

        self.is_clustered = True

        self.order = kwargs.get("order", 2)
        self.lags = kwargs.get("lags", None)
        self.alpha_cut = kwargs.get('alpha_cut', 0.0)

        self.shortname = "ClusteredMVFTS"
        self.name = "Clustered Multivariate FTS"

        self.pre_fuzzyfy = kwargs.get('pre_fuzzyfy', True)
        self.fuzzyfy_mode = kwargs.get('fuzzyfy_mode', 'sets')

    def fuzzyfy(self,data):
        ndata = []
        for index, row in data.iterrows() if isinstance(data, pd.DataFrame) else enumerate(data):
            data_point = self.format_data(row)
            ndata.append(self.partitioner.fuzzyfy(data_point, mode=self.fuzzyfy_mode))

        return ndata

    def train(self, data, **kwargs):

        self.fts_params['order'] = self.order

        self.model = self.fts_method(partitioner=self.partitioner, **self.fts_params)

        ndata = self.check_data(data)

        self.model.train(ndata, fuzzyfied=self.pre_fuzzyfy)

        self.partitioner.prune()

    def check_data(self, data):
        if self.pre_fuzzyfy:
            ndata = self.fuzzyfy(data)
        else:
            ndata = [self.format_data(k) for k in data.to_dict('records')]

        return ndata

    def forecast(self, ndata, **kwargs):

        ndata = self.check_data(ndata)

        pre_fuzz = kwargs.get('pre_fuzzyfy', self.pre_fuzzyfy)

        return self.model.forecast(ndata, fuzzyfied=pre_fuzz, **kwargs)

    def forecast_interval(self, data, **kwargs):

        if not self.model.has_interval_forecasting:
            raise Exception("The internal method does not support interval forecasting!")

        data = self.check_data(data)

        pre_fuzz = kwargs.get('pre_fuzzyfy', self.pre_fuzzyfy)

        return self.model.forecast_interval(data, fuzzyfied=pre_fuzz, **kwargs)



    def forecast_distribution(self, data, **kwargs):

        if not self.model.has_probability_forecasting:
            raise Exception("The internal method does not support probabilistic forecasting!")

        data = self.check_data(data)

        pre_fuzz = kwargs.get('pre_fuzzyfy', self.pre_fuzzyfy)

        return self.model.forecast_distribution(data, fuzzyfied=pre_fuzz, **kwargs)

    def forecast_ahead_distribution(self, data, steps, **kwargs):

        generators = kwargs.get('generators', None)

        if generators is None:
            raise Exception('You must provide parameter \'generators\'! generators is a dict where the keys' +
                            ' are the dataframe column names (except the target_variable) and the values are ' +
                            'lambda functions that accept one value (the actual value of the variable) '
                            ' and return the next value or trained FTS models that accept the actual values and '
                            'forecast new ones.')

        ndata = self.apply_transformations(data)

        start = kwargs.get('start_at', 0)

        ret = []
        sample = ndata.iloc[start: start + self.max_lag]
        for k in np.arange(0, steps):
            tmp = self.forecast_distribution(sample.iloc[-self.max_lag:], **kwargs)[0]

            ret.append(tmp)

            new_data_point = {}

            for data_label in generators.keys():
                if data_label != self.target_variable.data_label:
                    if isinstance(generators[data_label], LambdaType):
                        last_data_point = sample.iloc[-1]
                        new_data_point[data_label] = generators[data_label](last_data_point[data_label])

                    elif isinstance(generators[data_label], fts.FTS):
                        gen_model = generators[data_label]
                        last_data_point = sample.iloc[-gen_model.order:]

                        if not gen_model.is_multivariate:
                            last_data_point = last_data_point[data_label].values

                        new_data_point[data_label] = gen_model.forecast(last_data_point)[0]

            new_data_point[self.target_variable.data_label] = tmp.expected_value()

            sample = sample.append(new_data_point, ignore_index=True)

        return ret[-steps:]

    def forecast_multivariate(self, data, **kwargs):

        ndata = self.check_data(data)

        generators = kwargs.get('generators', {})

        already_processed_cols = []

        ret = {}

        ret[self.target_variable.data_label] = self.model.forecast(ndata, fuzzyfied=self.pre_fuzzyfy, **kwargs)

        for var in self.explanatory_variables:
            if var.data_label not in already_processed_cols:
                if var.data_label in generators:
                    if isinstance(generators[var.data_label], LambdaType):
                        fx = generators[var.data_label]
                        if len(data[var.data_label].values) > self.order:
                            ret[var.data_label] = [fx(k) for k in data[var.data_label].values[self.order:]]
                        else:
                            ret[var.data_label] = [fx(data[var.data_label].values[-1])]
                    elif isinstance(generators[var.data_label], fts.FTS):
                        model = generators[var.data_label]
                        if not model.is_multivariate:
                            ret[var.data_label] = model.forecast(data[var.data_label].values)
                        else:
                            ret[var.data_label] = model.forecast(data)
                elif self.target_variable.name != var.name:
                    self.target_variable = var
                    self.partitioner.change_target_variable(var)
                    self.model.partitioner = self.partitioner
                    self.model.reset_calculated_values()
                    ret[var.data_label] = self.model.forecast(ndata, fuzzyfied=self.pre_fuzzyfy, **kwargs)

                already_processed_cols.append(var.data_label)

        return pd.DataFrame(ret, columns=ret.keys())

    def forecast_ahead_multivariate(self, data, steps, **kwargs):

        ndata = self.apply_transformations(data)

        start = kwargs.get('start_at', 0)

        ret = ndata.iloc[start:self.order+start]

        for k in np.arange(0, steps):
            sample = ret.iloc[k:self.order+k]
            tmp = self.forecast_multivariate(sample, **kwargs)
            ret = ret.append(tmp, ignore_index=True)

        return ret

    def __str__(self):
        """String representation of the model"""
        return str(self.model)

    def __len__(self):
        """
        The length (number of rules) of the model

        :return: number of rules
        """
        return len(self.model)

