"""
Distributed Evolutionary Hyperparameter Optimization (DEHO) for MVFTS
"""

import numpy as np
import pandas as pd
import math
import time
from functools import reduce
from operator import itemgetter
import dispy

import random
from pyFTS.common import Util
from pyFTS.benchmarks import Measures
from pyFTS.partitioners import Grid, Entropy  # , Huarng
from pyFTS.common import Membership
from pyFTS.models import hofts, ifts, pwfts
from pyFTS.hyperparam import Util as hUtil
from pyFTS.distributed import dispy as dUtil

__measures = ['f1', 'f2', 'rmse', 'size']


def genotype(mf, npart, partitioner, order, alpha, lags, f1, f2):
    """
    Create the individual genotype

    :param mf: membership function
    :param npart: number of partitions
    :param partitioner: partitioner method
    :param order: model order
    :param alpha: alpha-cut
    :param lags: array with lag indexes
    :param f1: accuracy fitness value
    :param f2: parsimony fitness value
    :return: the genotype, a dictionary with all hyperparameters
    """
    ind = dict(mf=mf, npart=npart, partitioner=partitioner, order=order,
               alpha=alpha, lags=lags, f1=f1, f2=f2)
    return ind


def random_genotype(**kwargs):
    """
    Create random genotype

    :return: the genotype, a dictionary with all hyperparameters
    """
    order = random.randint(1, 3)
    lags = [k for k in np.arange(1, order+1)]
    return genotype(
        random.randint(1, 4),
        random.randint(10, 100),
        random.randint(1, 2),
        order,
        random.uniform(0, .5),
        lags,
        None,
        None
    )


#
def initial_population(n, **kwargs):
    """
    Create a random population of size n

    :param n: the size of the population
    :return: a list with n random individuals
    """

    create_random_individual = kwargs.get('random_individual', random_genotype)

    pop = []
    for i in range(n):
        pop.append(create_random_individual(**kwargs))
    return pop


def phenotype(individual, train, fts_method, parameters={}, **kwargs):
    """
    Instantiate the genotype, creating a fitted model with the genotype hyperparameters

    :param individual: a genotype
    :param train: the training dataset
    :param fts_method: the FTS method 
    :param parameters: dict with model specific arguments for fit method.
    :return: a fitted FTS model
    """
    from pyFTS.models import hofts, ifts, pwfts

    if individual['mf'] == 1:
        mf = Membership.trimf
    elif individual['mf'] == 2:
        mf = Membership.trapmf
    elif individual['mf'] == 3 and individual['partitioner'] != 2:
        mf = Membership.gaussmf
    else:
        mf = Membership.trimf

    if individual['partitioner'] == 1:
        partitioner = Grid.GridPartitioner(data=train, npart=individual['npart'], func=mf)
    elif individual['partitioner'] == 2:
        partitioner = Entropy.EntropyPartitioner(data=train, npart=individual['npart'], func=mf)

    model = fts_method(partitioner=partitioner,
                                       lags=individual['lags'],
                                       alpha_cut=individual['alpha'],
                                       order=individual['order'])

    model.fit(train, **parameters)

    return model


def evaluate(dataset, individual, **kwargs):
    """
    Evaluate an individual using a sliding window cross validation over the dataset.

    :param dataset: Evaluation dataset
    :param individual: genotype to be tested
    :param window_size: The length of scrolling window for train/test on dataset
    :param train_rate: The train/test split ([0,1])
    :param increment_rate: The increment of the scrolling window, relative to the window_size ([0,1])
    :param parameters: dict with model specific arguments for fit method.
    :return: a tuple (len_lags, rmse) with the parsimony fitness value and the accuracy fitness value
    """
    from pyFTS.models import hofts, ifts, pwfts
    from pyFTS.common import Util
    from pyFTS.benchmarks import Measures
    from pyFTS.hyperparam.Evolutionary import phenotype, __measures
    import numpy as np

    window_size = kwargs.get('window_size', 800)
    train_rate = kwargs.get('train_rate', .8)
    increment_rate = kwargs.get('increment_rate', .2)
    fts_method = kwargs.get('fts_method', hofts.WeightedHighOrderFTS)
    parameters = kwargs.get('parameters',{})

    if individual['f1'] is not None and individual['f2'] is not None:
        return { key: individual[key] for key in __measures }

    errors = []
    lengths = []

    for count, train, test in Util.sliding_window(dataset, window_size, train=train_rate, inc=increment_rate):

        try:

            model = phenotype(individual, train, fts_method=fts_method, parameters=parameters)

            forecasts = model.predict(test)

            rmse = Measures.rmse(test[model.max_lag:], forecasts[:-1])
            lengths.append(len(model))

            errors.append(rmse)

        except:
            lengths.append(np.nan)
            errors.append(np.nan)

    try:
        _lags = sum(model.lags) * 100

        _rmse = np.nanmean(errors)
        _len = np.nanmean(lengths)

        f1 = np.nansum([.6 * _rmse, .4 * np.nanstd(errors)])
        f2 = np.nansum([.4 * _len, .6 * _lags])

        return {'f1': f1, 'f2': f2, 'rmse': _rmse, 'size': _len }
    except:
        return {'f1': np.inf, 'f2': np.inf, 'rmse': np.inf, 'size': np.inf}


def tournament(population, objective, **kwargs):
    """
    Simple tournament selection strategy.

    :param population: the population
    :param objective: the objective to be considered on tournament
    :return:
    """
    n = len(population) - 1

    r1 = random.randint(0, n) if n > 2 else 0
    r2 = random.randint(0, n) if n > 2 else 1
    ix = r1 if population[r1][objective] < population[r2][objective] else r2
    return population[ix]


def double_tournament(population, **kwargs):
    """
    Double tournament selection strategy.

    :param population:
    :return:
    """

    ancestor1 = tournament(population, 'f1')
    ancestor2 = tournament(population, 'f1')

    selected = tournament([ancestor1, ancestor2], 'f2')

    return selected


def lag_crossover2(best, worst):
    """
    Cross over two lag genes

    :param best: best genotype
    :param worst: worst genotype
    :return: a tuple (order, lags)
    """
    order = int(round(.7 * best['order'] + .3 * worst['order']))
    lags = []

    min_order = min(best['order'], worst['order'])

    max_order = best if best['order'] > min_order else worst

    for k in np.arange(0, order):
        if k < min_order:
            lags.append(int(round(.7 * best['lags'][k] + .3 * worst['lags'][k])))
        else:
            lags.append(max_order['lags'][k])

    for k in range(1, order):
        while lags[k - 1] >= lags[k]:
            lags[k] += random.randint(1, 10)

    return order, lags


def crossover(population, **kwargs):
    """
    Crossover operation between two parents

    :param population: the original population
    :return: a genotype
    """
    import random

    n = len(population) - 1

    r1, r2 = 0, 0
    while r1 == r2:
        r1 = random.randint(0, n)
        r2 = random.randint(0, n)

    if population[r1]['f1'] < population[r2]['f1']:
        best = population[r1]
        worst = population[r2]
    else:
        best = population[r2]
        worst = population[r1]

    npart = int(round(.7 * best['npart'] + .3 * worst['npart']))
    alpha = float(.7 * best['alpha'] + .3 * worst['alpha'])

    rnd = random.uniform(0, 1)
    mf = best['mf'] if rnd < .7 else worst['mf']

    rnd = random.uniform(0, 1)
    partitioner = best['partitioner'] if rnd < .7 else worst['partitioner']

    order, lags = lag_crossover2(best, worst)

    descendent = genotype(mf, npart, partitioner, order, alpha, lags, None, None)

    return descendent


def mutation_lags(lags, order):
    """
    Mutation operation for lags gene

    :param lags:
    :param order:
    :return:
    """
    try:
        l = len(lags)
        new = []
        for lag in np.arange(order):
            if lag < l:
                new.append( min(50, max(1, int(lags[lag] + np.random.randint(-5, 5)))) )
            else:
                new.append( new[-1] + np.random.randint(1, 5) )

        if order > 1:
            for k in np.arange(1, order):
                while new[k] <= new[k - 1]:
                    new[k] = int(new[k] + np.random.randint(1, 5))

        return new
    except Exception as ex:
        print(lags, order, new, lag)


def mutation(individual, **kwargs):
    """
    Mutation operator

    :param individual: an individual genotype
    :param pmut: individual probability o
    :return:
    """

    individual['npart'] = min(50, max(3, int(individual['npart'] + np.random.normal(0, 4))))
    individual['alpha'] = min(.5, max(0, individual['alpha'] + np.random.normal(0, .5)))
    individual['mf'] = random.randint(1, 2)
    individual['partitioner'] = random.randint(1, 2)
    individual['order'] = min(5, max(1, int(individual['order'] + np.random.normal(0, 1))))
    # Chama a função mutation_lags
    individual['lags'] = mutation_lags( individual['lags'],  individual['order'])

    individual['f1'] = None
    individual['f2'] = None

    return individual


def elitism(population, new_population, **kwargs):
    """
    Elitism operation, always select the best individual of the population and discard the worst

    :param population:
    :param new_population:
    :return:
    """
    population = sorted(population, key=itemgetter('f1'))
    best = population[0]

    new_population = sorted(new_population, key=itemgetter('f1'))
    if new_population[0]["f1"] > best["f1"]:
        new_population.insert(0,best)
    elif new_population[0]["f1"] == best["f1"] and new_population[0]["f2"] > best["f2"]:
        new_population.insert(0, best)

    return new_population


def GeneticAlgorithm(dataset, **kwargs):
    """
    Genetic algoritm for Distributed Evolutionary Hyperparameter Optimization (DEHO)

    :param dataset: The time series to optimize the FTS
    :keyword ngen: An integer value with the maximum number of generations, default value: 30
    :keyword mgen: An integer value with the maximum number of generations without improvement to stop, default value 7
    :keyword npop: An integer value with the population size, default value: 20
    :keyword pcross: A float value between 0 and 1 with the probability of crossover, default: .5
    :keyword psel: A float value between 0 and 1 with the probability of selection, default: .5
    :keyword pmut: A float value between 0 and 1 with the probability of mutation, default: .3
    :keyword fts_method: The FTS method to optimize
    :keyword parameters: dict with model specific arguments for fts_method
    :keyword elitism: A boolean value indicating if the best individual must always survive to next population
    :keyword initial_operator: a function that receives npop and return a random population with size npop
    :keyword evalutation_operator: a function that receives a dataset and an individual and return its fitness
    :keyword selection_operator: a function that receives the whole population and return a selected individual
    :keyword crossover_operator: a function that receives the whole population and return a descendent individual
    :keyword mutation_operator: a function that receives one individual and return a changed individual
    :keyword window_size: An integer value with the the length of scrolling window for train/test on dataset
    :keyword train_rate: A float value between 0 and 1 with the train/test split ([0,1])
    :keyword increment_rate: A float value between 0 and 1 with the the increment of the scrolling window,
             relative to the window_size ([0,1])
    :keyword collect_statistics: A boolean value indicating to collect statistics for each generation
    :keyword distributed: A value indicating it the execution will be local and sequential (distributed=False),
             or parallel and distributed (distributed='dispy' or distributed='spark')
    :keyword cluster: If distributed='dispy' the list of cluster nodes, else if distributed='spark' it is the master node
    :return: the best genotype
    """

    statistics = []

    ngen = kwargs.get('ngen',30)
    mgen = kwargs.get('mgen', 7)
    npop = kwargs.get('npop',20)
    psel = kwargs.get('psel', .5)
    pcross = kwargs.get('pcross',.5)
    pmut = kwargs.get('pmut',.3)
    distributed = kwargs.get('distributed', False)

    initial_operator = kwargs.get('initial_operator', initial_population)
    evaluation_operator = kwargs.get('evaluation_operator', evaluate)
    selection_operator = kwargs.get('selection_operator', double_tournament)
    crossover_operator = kwargs.get('crossover_operator', crossover)
    mutation_operator = kwargs.get('mutation_operator', mutation)

    _elitism = kwargs.get('elitism', True)

    elitism_operator = kwargs.get('elitism_operator', elitism)

    if distributed == 'dispy':
        cluster = kwargs.pop('cluster', None)

    collect_statistics = kwargs.get('collect_statistics', True)

    no_improvement_count = 0

    new_population = []

    population = initial_operator(npop, **kwargs)

    last_best = population[0]
    best = population[1]

    print("Evaluating initial population {}".format(time.time()))
    if not distributed:
        for individual in population:
            ret = evaluation_operator(dataset, individual, **kwargs)
            for key in __measures:
                individual[key] = ret[key]
    elif distributed=='dispy':
        jobs = []
        for ct, individual in enumerate(population):
            job = cluster.submit(dataset, individual, **kwargs)
            job.id = ct
            jobs.append(job)
        for job in jobs:
            result = job()
            if job.status == dispy.DispyJob.Finished and result is not None:
                for key in __measures:
                    population[job.id][key] = result[key]
            else:
                print(job.exception)
                print(job.stdout)

    for i in range(ngen):
        print("GENERATION {} {}".format(i, time.time()))

        generation_statistics = {}

        # Selection
        for j in range(int(npop * psel)):
            new_population.append(selection_operator(population, **kwargs))

        # Crossover
        new = []
        for j in range(int(npop * pcross)):
            new.append(crossover_operator(new_population, **kwargs))

        new_population.extend(new)

        # Mutation
        for ct, individual in enumerate(new_population):
            rnd = random.uniform(0, 1)
            if rnd < pmut:
                new_population[ct] = mutation_operator(individual, **kwargs)

        # Evaluation
        if collect_statistics:
            stats = {}
            for key in __measures:
                stats[key] = []

        if not distributed:
            for individual in new_population:
                ret = evaluation_operator(dataset, individual, **kwargs)
                for key in __measures:
                    individual[key] = ret[key]
                    if collect_statistics: stats[key].append(ret[key])

        elif distributed == 'dispy':
            jobs = []

            for ct, individual in enumerate(new_population):
                job = cluster.submit(dataset, individual, **kwargs)
                job.id = ct
                jobs.append(job)
            for job in jobs:
                print('job id {}'.format(job.id))
                result = job()
                if job.status == dispy.DispyJob.Finished and result is not None:
                    for key in __measures:
                        new_population[job.id][key] = result[key]
                        if collect_statistics: stats[key].append(result[key])
                else:
                    print(job.exception)
                    print(job.stdout)


        if collect_statistics:
            mean_stats = {key: np.nanmedian(stats[key]) for key in __measures }

            generation_statistics['population'] = mean_stats

        # Elitism
        if _elitism:
            population = elitism_operator(population, new_population, **kwargs)

        population = population[:npop]

        new_population = []

        last_best = best

        best = population[0]

        if collect_statistics:
            generation_statistics['best'] = {key: best[key] for key in __measures }

            statistics.append(generation_statistics)

        if last_best['f1'] <= best['f1'] and last_best['f2'] <= best['f2']:
            no_improvement_count += 1
            print("WITHOUT IMPROVEMENT {}".format(no_improvement_count))
            pmut += .05
        else:
            no_improvement_count = 0
            pcross = kwargs.get('pcross', .5)
            pmut = kwargs.get('pmut', .3)
            print(best)

        if no_improvement_count == mgen:
            break

    return best, statistics


def process_experiment(fts_method, result, datasetname, conn):
    """
    Persist the results of an DEHO execution in sqlite database (best hyperparameters) and json file (generation statistics)

    :param fts_method:
    :param result:
    :param datasetname:
    :param conn:
    :return:
    """

    log_result(conn, datasetname, fts_method, result['individual'])
    persist_statistics(datasetname, result['statistics'])
    return result['individual']


def persist_statistics(datasetname, statistics):
    import json
    with open('statistics_{}.json'.format(datasetname), 'w') as file:
        file.write(json.dumps(statistics))


def log_result(conn, datasetname, fts_method, result):
    metrics = ['rmse', 'size', 'time']
    for metric in metrics:
        record = (datasetname, 'Evolutive', fts_method, None, result['mf'],
                  result['order'], result['partitioner'], result['npart'],
                  result['alpha'], str(result['lags']), metric, result[metric])

        print(record)

        hUtil.insert_hyperparam(record, conn)


def execute(datasetname, dataset, **kwargs):
    """
    Batch execution of Distributed Evolutionary Hyperparameter Optimization (DEHO) for monovariate methods

    :param datasetname:
    :param dataset: The time series to optimize the FTS
    :keyword database_file:
    :keyword experiments:
    :keyword distributed:
    :keyword ngen: An integer value with the maximum number of generations, default value: 30
    :keyword mgen: An integer value with the maximum number of generations without improvement to stop, default value 7
    :keyword npop: An integer value with the population size, default value: 20
    :keyword pcross: A float value between 0 and 1 with the probability of crossover, default: .5
    :keyword psel: A float value between 0 and 1 with the probability of selection, default: .5
    :keyword pmut: A float value between 0 and 1 with the probability of mutation, default: .3
    :keyword fts_method: The FTS method to optimize
    :keyword parameters: dict with model specific arguments for fts_method
    :keyword elitism: A boolean value indicating if the best individual must always survive to next population
    :keyword initial_operator: a function that receives npop and return a random population with size npop
    :keyword random_individual: create an random genotype
    :keyword evalutation_operator: a function that receives a dataset and an individual and return its fitness
    :keyword selection_operator: a function that receives the whole population and return a selected individual
    :keyword crossover_operator: a function that receives the whole population and return a descendent individual
    :keyword mutation_operator: a function that receives one individual and return a changed individual
    :keyword window_size: An integer value with the the length of scrolling window for train/test on dataset
    :keyword train_rate: A float value between 0 and 1 with the train/test split ([0,1])
    :keyword increment_rate: A float value between 0 and 1 with the the increment of the scrolling window,
             relative to the window_size ([0,1])
    :keyword collect_statistics: A boolean value indicating to collect statistics for each generation
    :keyword distributed: A value indicating it the execution will be local and sequential (distributed=False),
             or parallel and distributed (distributed='dispy' or distributed='spark')
    :keyword cluster: If distributed='dispy' the list of cluster nodes, else if distributed='spark' it is the master node
    :return: the best genotype
    """

    file = kwargs.get('database_file', 'hyperparam.db')

    conn = hUtil.open_hyperparam_db(file)

    experiments = kwargs.get('experiments', 30)

    distributed = kwargs.get('distributed', False)

    fts_method = kwargs.get('fts_method', hofts.WeightedHighOrderFTS)
    shortname = str(fts_method.__module__).split('.')[-1]

    if distributed == 'dispy':
        nodes = kwargs.get('nodes', ['127.0.0.1'])
        cluster, http_server = dUtil.start_dispy_cluster(evaluate, nodes=nodes)
        kwargs['cluster'] = cluster

    ret = []
    for i in np.arange(experiments):
        print("Experiment {}".format(i))

        start = time.time()
        ret, statistics = GeneticAlgorithm(dataset, **kwargs)
        end = time.time()
        ret['time'] = end - start
        experiment = {'individual': ret, 'statistics': statistics}

        ret = process_experiment(shortname, experiment, datasetname, conn)

    if distributed == 'dispy':
        dUtil.stop_dispy_cluster(cluster, http_server)

    return ret
