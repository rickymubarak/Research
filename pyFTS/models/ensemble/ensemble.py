"""
EnsembleFTS wraps several FTS methods to ensemble their forecasts, providing point,
interval and probabilistic forecasting.

Silva, P. C. L et al. Probabilistic Forecasting with Seasonal Ensemble Fuzzy Time-Series
XIII Brazilian Congress on Computational Intelligence, 2017. Rio de Janeiro, Brazil.
"""


import numpy as np
import pandas as pd
from pyFTS.common import SortedCollection, fts, tree
from pyFTS.models import chen, cheng, hofts, hwang, ismailefendi, sadaei, song, yu
from pyFTS.probabilistic import ProbabilityDistribution
from pyFTS.partitioners import Grid
import scipy.stats as st
from itertools import product


def sampler(data, quantiles, bounds=False):
    ret = []
    for qt in quantiles:
        ret.append(np.nanpercentile(data, q=qt * 100))
    if bounds:
        ret.insert(0, min(data))
        ret.append(max(data))
    return ret


class EnsembleFTS(fts.FTS):
    """
    Ensemble FTS
    """
    def __init__(self, **kwargs):
        super(EnsembleFTS, self).__init__(**kwargs)
        self.shortname = "EnsembleFTS"
        self.name = "Ensemble FTS"
        self.flrgs = {}
        self.is_wrapper = True
        self.has_point_forecasting = True
        self.has_interval_forecasting = True
        self.has_probability_forecasting = True
        self.is_high_order = True
        self.models = []
        """A list of FTS models, the ensemble components"""
        self.parameters = []
        """A list with the parameters for each component model"""
        self.alpha = kwargs.get("alpha", 0.05)
        """The quantiles """
        self.point_method = kwargs.get('point_method', 'mean')
        """The method used to mix the several model's forecasts into a unique point forecast. Options: mean, median, quantile, exponential"""
        self.interval_method = kwargs.get('interval_method', 'quantile')
        """The method used to mix the several model's forecasts into a interval forecast. Options: quantile, extremum, normal"""

    def append_model(self, model):
        """
        Append a new trained model to the ensemble

        :param model: FTS model

        """
        self.models.append(model)
        if model.order > self.order:
            self.order = model.order

        if model.is_multivariate:
            self.is_multivariate = True

        if model.has_seasonality:
            self.has_seasonality = True

        if model.original_min < self.original_min:
            self.original_min = model.original_min
        elif model.original_max > self.original_max:
            self.original_max = model.original_max


    def get_UoD(self):
        return [self.original_min, self.original_max]

    def train(self, data, **kwargs):
        pass

    def get_models_forecasts(self,data):
        tmp = []
        for model in self.models:
            if model.is_multivariate or model.has_seasonality:
                forecast = model.forecast(data)
            else:

                if isinstance(data, pd.DataFrame) and self.indexer is not None:
                    data = self.indexer.get_data(data)

                sample = data[-model.order:]
                forecast = model.predict(sample)
                if isinstance(forecast, (list,np.ndarray)) and len(forecast) > 0:
                    forecast = forecast[-1]
                elif isinstance(forecast, (list,np.ndarray)) and len(forecast) == 0:
                    forecast = np.nan
            if isinstance(forecast, list):
                tmp.extend(forecast)
            else:
                tmp.append(forecast)
        return tmp

    def get_point(self,forecasts, **kwargs):
        if self.point_method == 'mean':
            ret = np.nanmean(forecasts)
        elif self.point_method == 'median':
            ret = np.nanpercentile(forecasts, 50)
        elif self.point_method == 'quantile':
            alpha = kwargs.get("alpha",0.05)
            ret = np.nanpercentile(forecasts, alpha*100)
        elif self.point_method == 'exponential':
            l = len(self.models)
            if l == 1:
                return forecasts[0]
            w = np.array([np.exp(-(l - k)) for k in range(l)])
            w = w / np.nansum(w)
            ret = np.nansum([w[k] * forecasts[k] for k in range(l)])

        return ret

    def get_interval(self, forecasts):
        ret = []
        if self.interval_method == 'extremum':
            ret.append([min(forecasts), max(forecasts)])
        elif self.interval_method == 'quantile':
            qt_lo = np.nanpercentile(forecasts, q=self.alpha * 100)
            qt_up = np.nanpercentile(forecasts, q=(1-self.alpha) * 100)
            ret.append([qt_lo, qt_up])
        elif self.interval_method == 'normal':
            mu = np.nanmean(forecasts)
            sigma = np.sqrt(np.nanvar(forecasts))
            ret.append(mu + st.norm.ppf(self.alpha) * sigma)
            ret.append(mu + st.norm.ppf(1 - self.alpha) * sigma)

        return ret

    def get_distribution_interquantile(self,forecasts, alpha):
        size = len(forecasts)
        qt_lower = int(np.ceil(size * alpha)) - 1
        qt_upper = int(np.ceil(size * (1- alpha))) - 1

        ret = sorted(forecasts)[qt_lower : qt_upper]

        return ret

    def forecast(self, data, **kwargs):

        if "method" in kwargs:
            self.point_method = kwargs.get('method','mean')

        l = len(data)
        ret = []

        for k in np.arange(self.order, l+1):
            sample = data[k - self.max_lag : k]
            tmp = self.get_models_forecasts(sample)
            point = self.get_point(tmp)
            ret.append(point)

        return ret

    def forecast_interval(self, data, **kwargs):

        if "method" in kwargs:
            self.interval_method = kwargs.get('method','quantile')

        self.alpha = kwargs.get('alpha', self.alpha)

        l = len(data)

        ret = []

        for k in np.arange(self.order, l+1):
            sample = data[k - self.order : k]
            tmp = self.get_models_forecasts(sample)
            interval = self.get_interval(tmp)
            if len(interval) == 1:
                interval = interval[-1]
            ret.append(interval)

        return ret

    def forecast_ahead_interval(self, data, steps, **kwargs):

        if 'method' in kwargs:
            self.interval_method = kwargs.get('method','quantile')

        self.alpha = kwargs.get('alpha', self.alpha)

        ret = []

        start = kwargs.get('start_at', self.order)

        sample = [[k] for k in data[start: start+self.order]]

        for k in np.arange(self.order, steps + self.order):
            forecasts = []

            lags = []
            for i in np.arange(0, self.order):
                lags.append(sample[i - self.order])

            # Trace the possible paths
            for path in product(*lags):
                forecasts.extend(self.get_models_forecasts(path))

            sample.append(sampler(forecasts, np.arange(.1, 1, 0.1), bounds=True))

            interval = self.get_interval(forecasts)

            if len(interval) == 1:
                interval = interval[0]

            ret.append(interval)

        return ret[-steps:]

    def forecast_distribution(self, data, **kwargs):
        ret = []

        smooth = kwargs.get("smooth", "KDE")
        alpha = kwargs.get("alpha", None)

        uod = self.get_UoD()

        for k in np.arange(self.order, len(data)):

            sample = data[k-self.order : k]

            forecasts = self.get_models_forecasts(sample)

            if alpha is None:
                forecasts = np.ravel(forecasts).tolist()
            else:
                forecasts = self.get_distribution_interquantile(np.ravel(forecasts).tolist(), alpha)

            dist = ProbabilityDistribution.ProbabilityDistribution(smooth, uod=uod, data=forecasts,
                                                                   name="", **kwargs)

            ret.append(dist)

        return ret

    def forecast_ahead_distribution(self, data, steps, **kwargs):
        if 'method' in kwargs:
            self.point_method = kwargs.get('method','mean')

        smooth = kwargs.get("smooth", "histogram")
        alpha = kwargs.get("alpha", None)

        ret = []

        start = kwargs.get('start_at', self.order)

        uod = self.get_UoD()

        sample = [[k] for k in data[start: start+self.order]]

        for k in np.arange(self.order, steps+self.order):
            forecasts = []

            lags = []
            for i in np.arange(0, self.order):
                lags.append(sample[i - self.order])

            # Trace the possible paths
            for path in product(*lags):
                forecasts.extend(self.get_models_forecasts(path))

            sample.append(sampler(forecasts, np.arange(.1, 1, 0.1), bounds=True))

            if alpha is None:
                forecasts = np.ravel(forecasts).tolist()
            else:
                forecasts = self.get_distribution_interquantile(np.ravel(forecasts).tolist(), alpha)

            dist = ProbabilityDistribution.ProbabilityDistribution(smooth, uod=uod, data=forecasts,
                                                                   name="", **kwargs)

            ret.append(dist)

        return ret[-steps:]


class SimpleEnsembleFTS(EnsembleFTS):
    '''
    An homogeneous FTS method ensemble with variations on partitionings and orders.
    '''
    def __init__(self, **kwargs):
        super(SimpleEnsembleFTS, self).__init__(**kwargs)
        self.method = kwargs.get('fts_method', hofts.WeightedHighOrderFTS)
        """FTS method class that will be used on internal models"""
        self.partitioner_method = kwargs.get('partitioner_method', Grid.GridPartitioner)
        """UoD partitioner class that will be used on internal methods"""
        self.partitions = kwargs.get('partitions', np.arange(15,35,10))
        """Possible variations of number of partitions on internal models"""
        self.orders = kwargs.get('orders', [1,2,3])
        """Possible variations of order on internal models"""
        self.uod_clip = False

        self.shortname = kwargs.get('name', 'EnsembleFTS-' + str(self.method.__module__).split('.')[-1])

    def train(self, data, **kwargs):
        for k in self.partitions:
            fs = self.partitioner_method(data=data, npart=k)

            for order in self.orders:
                tmp = self.method(partitioner=fs, order=order)

                tmp.fit(data)

                self.append_model(tmp)


class AllMethodEnsembleFTS(EnsembleFTS):
    """
    Creates an EnsembleFTS with all point forecast methods, sharing the same partitioner
    """
    def __init__(self, **kwargs):
        super(AllMethodEnsembleFTS, self).__init__(**kwargs)
        self.min_order = 3
        self.shortname ="Ensemble FTS"

    def set_transformations(self, model):
        for t in self.transformations:
            model.append_transformation(t)

    def train(self, data, **kwargs):
        fo_methods = [song.ConventionalFTS, chen.ConventionalFTS, yu.WeightedFTS, cheng.TrendWeightedFTS,
                      sadaei.ExponentialyWeightedFTS, ismailefendi.ImprovedWeightedFTS]

        ho_methods = [hofts.HighOrderFTS, hwang.HighOrderFTS]

        for method in fo_methods:
            model = method(partitioner=self.partitioner)
            self.set_transformations(model)
            model.fit(data, **kwargs)
            self.append_model(model)

        for method in ho_methods:
            for o in np.arange(1, self.order+1):
                model = method(partitioner=self.partitioner)
                if model.min_order >= o:
                    model.order = o
                    self.set_transformations(model)
                    model.fit(data, **kwargs)
                    self.append_model(model)




