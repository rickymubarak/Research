from pyFTS.models.multivariate import cmvfts, grid
from pyFTS.models import hofts


class GranularWMVFTS(cmvfts.ClusteredMVFTS):
    """
    Granular multivariate weighted high order FTS
    """

    def __init__(self, **kwargs):
        super(GranularWMVFTS, self).__init__(**kwargs)

        self.fts_method = kwargs.get('fts_method', hofts.WeightedHighOrderFTS)
        self.model = None
        """The most recent trained model"""
        self.knn = kwargs.get('knn', 2)
        self.order = kwargs.get("order", 2)
        self.shortname = "FIG-FTS"
        self.name = "Fuzzy Information Granular FTS"
        self.mode = kwargs.get('mode','sets')

    def train(self, data, **kwargs):
        self.partitioner = grid.IncrementalGridCluster(
            explanatory_variables=self.explanatory_variables,
            target_variable=self.target_variable,
            neighbors=self.knn)
        super(GranularWMVFTS, self).train(data, mode=self.mode, **kwargs)

