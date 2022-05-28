"""
Facilities for pyFTS Benchmark module
"""

import matplotlib as plt
import matplotlib.cm as cmx
import matplotlib.colors as pltcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sqlite3
#from mpl_toolkits.mplot3d import Axes3D


from copy import deepcopy
from pyFTS.common import Util


def open_benchmark_db(name):
    """
    Open a connection with a Sqlite database designed to store benchmark results.

    :param name: database filenem
    :return: a sqlite3 database connection
    """
    conn = sqlite3.connect(name)

    #performance optimizations
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    create_benchmark_tables(conn)
    return conn


def create_benchmark_tables(conn):
    """
    Create a sqlite3 table designed to store benchmark results.

    :param conn: a sqlite3 database connection
    """
    c = conn.cursor()

    c.execute('''CREATE TABLE if not exists benchmarks(
                 ID integer primary key, Date int, Dataset text, Tag text, 
                 Type text, Model text, Transformation text, 'Order' int, 
                 Scheme text, Partitions int,
                 Size int, Steps int, Method text, Measure text, Value real)''')

    conn.commit()


def insert_benchmark(data, conn):
    """
    Insert benchmark data on database

    :param data: a tuple with the benchmark data with format:

    ID: integer incremental primary key
    Date: Date/hour of benchmark execution
    Dataset: Identify on which dataset the dataset was performed
    Tag: a user defined word that indentify a benchmark set
    Type: forecasting type (point, interval, distribution)
    Model: FTS model
    Transformation: The name of data transformation, if one was used
    Order: the order of the FTS method
    Scheme: UoD partitioning scheme
    Partitions: Number of partitions
    Size: Number of rules of the FTS model
    Steps: prediction horizon, i. e., the number of steps ahead
    Measure: accuracy measure
    Value: the measure value

    :param conn: a sqlite3 database connection
    :return:
    """
    c = conn.cursor()

    c.execute("INSERT INTO benchmarks(Date, Dataset, Tag, Type, Model, "
              + "Transformation, 'Order', Scheme, Partitions, "
              + "Size, Steps, Method, Measure, Value) "
              + "VALUES(datetime('now'),?,?,?,?,?,?,?,?,?,?,?,?,?)", data)
    conn.commit()


def process_common_data(dataset, tag, type, job):
    """
    Wraps benchmark information on a tuple for sqlite database

    :param dataset: benchmark dataset
    :param tag: benchmark set alias
    :param type: forecasting type
    :param job: a dictionary with benchmark data
    :return: tuple for sqlite database
    """
    model = job["obj"]
    if model.benchmark_only:
        data = [dataset, tag, type, model.shortname,
                str(model.transformations[0]) if len(model.transformations) > 0 else None,
                model.order, None, None,
                None]
    else:
        data = [dataset, tag, type, model.shortname,
                str(model.partitioner.transformation) if model.partitioner.transformation is not None else None,
                model.order, model.partitioner.name, str(model.partitioner.partitions),
                len(model)]

    return data


def process_common_data2(dataset, tag, type, job):
    """
    Wraps benchmark information on a tuple for sqlite database

    :param dataset: benchmark dataset
    :param tag: benchmark set alias
    :param type: forecasting type
    :param job: a dictionary with benchmark data
    :return: tuple for sqlite database
    """
    data = [dataset, tag, type,
            job['model'],
            job['transformation'],
            job['order'],
            job['partitioner'],
            job['partitions'],
            job['size']
            ]

    return data


def get_dataframe_from_bd(file, filter):
    """
    Query the sqlite benchmark database and return a pandas dataframe with the results

    :param file: the url of the benchmark database
    :param filter: sql conditions to filter
    :return: pandas dataframe with the query results
    """
    con = sqlite3.connect(file)
    sql = "SELECT * from benchmarks"
    if filter is not None:
        sql += " WHERE " + filter
    return pd.read_sql_query(sql, con)



def extract_measure(dataframe, measure, data_columns):
    if not dataframe.empty:
        df = dataframe[(dataframe.Measure == measure)][data_columns]
        tmp = df.to_dict(orient="records")[0]
        ret = [k for k in tmp.values() if not np.isnan(k)]
        return ret
    else:
        return None


def find_best(dataframe, criteria, ascending):
    models = dataframe.Model.unique()
    orders = dataframe.Order.unique()
    ret = {}
    for m in models:
        for o in orders:
            mod = {}
            df = dataframe[(dataframe.Model == m) & (dataframe.Order == o)].sort_values(by=criteria, ascending=ascending)
            if not df.empty:
                _key = str(m) + str(o)
                best = df.loc[df.index[0]]
                mod['Model'] = m
                mod['Order'] = o
                mod['Scheme'] = best["Scheme"]
                mod['Partitions'] = best["Partitions"]

                ret[_key] = mod

    return ret


def simple_synthetic_dataframe(file, tag, measure, sql=None):
    '''
    Read experiments results from sqlite3 database in 'file', make a synthesis of the results
    of the metric 'measure' with the same 'tag', returning a Pandas DataFrame with the mean results.

    :param file: sqlite3 database file name
    :param tag: common tag of the experiments
    :param measure: metric to synthetize
    :return: Pandas DataFrame with the mean results
    '''
    df = get_dataframe_from_bd(file,"tag = '{}' and measure = '{}' {}"
                              .format(tag, measure,
                                      '' if sql is None else 'and {}'.format(sql)))
    data = []

    models = df.Model.unique()
    datasets = df.Dataset.unique()
    for dataset in datasets:
        for model in models:
            _filter = (df.Dataset == dataset) & (df.Model == model)
            avg = np.nanmean(df[_filter].Value)
            std = np.nanstd(df[_filter].Value)
            data.append([dataset, model, avg, std])

    dat = pd.DataFrame(data, columns=['Dataset', 'Model', 'AVG', 'STD'])
    dat = dat.sort_values(['AVG', 'STD'])

    best = []

    for dataset in datasets:
        for model in models:
            ix = dat[(dat.Dataset == dataset) & (dat.Model == model)].index[0]
            best.append(ix)

    ret = dat.loc[best].sort_values(['AVG', 'STD'])
    ret.groupby('Dataset')

    return ret


def analytic_tabular_dataframe(dataframe):
    experiments = len(dataframe.columns) - len(base_dataframe_columns()) - 1
    models = dataframe.Model.unique()
    orders = dataframe.Order.unique()
    schemes = dataframe.Scheme.unique()
    partitions = dataframe.Partitions.unique()
    steps = dataframe.Steps.unique()
    measures = dataframe.Measure.unique()
    data_columns = analytical_data_columns(experiments)

    ret = []

    for m in models:
        for o in orders:
            for s in schemes:
                for p in partitions:
                    for st in steps:
                        for ms in measures:
                            df = dataframe[(dataframe.Model == m) & (dataframe.Order == o)
                                           & (dataframe.Scheme == s) & (dataframe.Partitions == p)
                                           & (dataframe.Steps == st) & (dataframe.Measure == ms) ]

                            if not df.empty:
                                for col in data_columns:
                                    mod = [m, o, s, p, st, ms, df[col].values[0]]
                                    ret.append(mod)

    dat = pd.DataFrame(ret, columns=tabular_dataframe_columns())
    return dat


def tabular_dataframe_columns():
        return ["Model", "Order", "Scheme", "Partitions", "Steps", "Measure", "Value"]


def base_dataframe_columns():
    return ["Model", "Order", "Scheme", "Partitions", "Size", "Steps", "Method"]

def point_dataframe_synthetic_columns():
    return base_dataframe_columns().extend(["RMSEAVG", "RMSESTD",
            "SMAPEAVG", "SMAPESTD", "UAVG","USTD", "TIMEAVG", "TIMESTD"])


def point_dataframe_analytic_columns(experiments):
    columns = [str(k) for k in np.arange(0, experiments)]
    columns.insert(0, "Model")
    columns.insert(1, "Order")
    columns.insert(2, "Scheme")
    columns.insert(3, "Partitions")
    columns.insert(4, "Size")
    columns.insert(5, "Steps")
    columns.insert(6, "Method")
    columns.insert(7, "Measure")
    return columns


def save_dataframe_point(experiments, file, objs, rmse, save, synthetic, smape, times, u, steps, method):
    """
    Create a dataframe to store the benchmark results

    :param experiments: dictionary with the execution results
    :param file: 
    :param objs: 
    :param rmse: 
    :param save: 
    :param synthetic: 
    :param smape: 
    :param times: 
    :param u: 
    :return: 
    """
    ret = []

    if synthetic:

        for k in sorted(objs.keys()):
            try:
                mod = []
                mfts = objs[k]
                mod.append(mfts.shortname)
                mod.append(mfts.order)
                if not mfts.benchmark_only:
                    mod.append(mfts.partitioner.name)
                    mod.append(mfts.partitioner.partitions)
                    mod.append(len(mfts))
                else:
                    mod.append('-')
                    mod.append('-')
                    mod.append('-')
                mod.append(steps[k])
                mod.append(method[k])
                mod.append(np.round(np.nanmean(rmse[k]), 2))
                mod.append(np.round(np.nanstd(rmse[k]), 2))
                mod.append(np.round(np.nanmean(smape[k]), 2))
                mod.append(np.round(np.nanstd(smape[k]), 2))
                mod.append(np.round(np.nanmean(u[k]), 2))
                mod.append(np.round(np.nanstd(u[k]), 2))
                mod.append(np.round(np.nanmean(times[k]), 4))
                mod.append(np.round(np.nanstd(times[k]), 4))
                ret.append(mod)
            except Exception as ex:
                print("Erro ao salvar ", k)
                print("Exceção ", ex)

        columns = point_dataframe_synthetic_columns()
    else:
        for k in sorted(objs.keys()):
            try:
                mfts = objs[k]
                n = mfts.shortname
                o = mfts.order
                if not mfts.benchmark_only:
                    s = mfts.partitioner.name
                    p = mfts.partitioner.partitions
                    l = len(mfts)
                else:
                    s = '-'
                    p = '-'
                    l = '-'
                st = steps[k]
                mt = method[k]
                tmp = [n, o, s, p, l, st, mt, 'RMSE']
                tmp.extend(rmse[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'SMAPE']
                tmp.extend(smape[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'U']
                tmp.extend(u[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'TIME']
                tmp.extend(times[k])
                ret.append(deepcopy(tmp))
            except Exception as ex:
                print("Erro ao salvar ", k)
                print("Exceção ", ex)
        columns = point_dataframe_analytic_columns(experiments)
    try:
        dat = pd.DataFrame(ret, columns=columns)
        if save: dat.to_csv(Util.uniquefilename(file), sep=";", index=False)
        return dat
    except Exception as ex:
        print(ex)
        print(experiments)
        print(columns)
        print(ret)


def cast_dataframe_to_synthetic(infile, outfile, experiments, type):
    if type == 'point':
        analytic_columns = point_dataframe_analytic_columns
        synthetic_columns = point_dataframe_synthetic_columns
        synthetize_measures = cast_dataframe_to_synthetic_point
    elif type == 'interval':
        analytic_columns = interval_dataframe_analytic_columns
        synthetic_columns = interval_dataframe_synthetic_columns
        synthetize_measures = cast_dataframe_to_synthetic_interval
    elif type == 'distribution':
        analytic_columns = probabilistic_dataframe_analytic_columns
        synthetic_columns = probabilistic_dataframe_synthetic_columns
        synthetize_measures = cast_dataframe_to_synthetic_probabilistic
    else:
        raise ValueError("Type parameter has an unknown value!")

    columns = analytic_columns(experiments)
    dat = pd.read_csv(infile, sep=";", usecols=columns)
    models = dat.Model.unique()
    orders = dat.Order.unique()
    schemes = dat.Scheme.unique()
    partitions = dat.Partitions.unique()
    steps = dat.Steps.unique()
    methods = dat.Method.unique()

    data_columns = analytical_data_columns(experiments)

    ret = []

    for m in models:
        for o in orders:
            for s in schemes:
                for p in partitions:
                    for st in steps:
                        for mt in methods:
                            df = dat[(dat.Model == m) & (dat.Order == o) & (dat.Scheme == s) &
                                     (dat.Partitions == p) & (dat.Steps == st) & (dat.Method == mt)]
                            if not df.empty:
                                mod = synthetize_measures(df, data_columns)
                                mod.insert(0, m)
                                mod.insert(1, o)
                                mod.insert(2, s)
                                mod.insert(3, p)
                                mod.insert(4, df.iat[0,5])
                                mod.insert(5, st)
                                mod.insert(6, mt)
                                ret.append(mod)

    dat = pd.DataFrame(ret, columns=synthetic_columns())
    dat.to_csv(outfile, sep=";", index=False)


def cast_dataframe_to_synthetic_point(df, data_columns):
    ret = []
    rmse = extract_measure(df, 'RMSE', data_columns)
    smape = extract_measure(df, 'SMAPE', data_columns)
    u = extract_measure(df, 'U', data_columns)
    times = extract_measure(df, 'TIME', data_columns)
    ret.append(np.round(np.nanmean(rmse), 2))
    ret.append(np.round(np.nanstd(rmse), 2))
    ret.append(np.round(np.nanmean(smape), 2))
    ret.append(np.round(np.nanstd(smape), 2))
    ret.append(np.round(np.nanmean(u), 2))
    ret.append(np.round(np.nanstd(u), 2))
    ret.append(np.round(np.nanmean(times), 4))
    ret.append(np.round(np.nanstd(times), 4))

    return ret


def analytical_data_columns(experiments):
    data_columns = [str(k) for k in np.arange(0, experiments)]
    return data_columns


def scale_params(data):
    vmin = np.nanmin(data)
    vlen = np.nanmax(data) - vmin
    return (vmin, vlen)



def scale(data, params):
    ndata = [(k-params[0])/params[1] for k in data]
    return ndata


def stats(measure, data):
    print(measure, np.nanmean(data), np.nanstd(data))


def unified_scaled_point(experiments, tam, save=False, file=None,
                         sort_columns=['UAVG', 'RMSEAVG', 'USTD', 'RMSESTD'],
                         sort_ascend=[1, 1, 1, 1],save_best=False,
                         ignore=None, replace=None):

    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=tam)

    axes[0].set_title('RMSE')
    axes[1].set_title('SMAPE')
    axes[2].set_title('U Statistic')

    models = {}

    for experiment in experiments:

        mdl = {}

        dat_syn = pd.read_csv(experiment[0], sep=";", usecols=point_dataframe_synthetic_columns())

        bests = find_best(dat_syn, sort_columns, sort_ascend)

        dat_ana = pd.read_csv(experiment[1], sep=";", usecols=point_dataframe_analytic_columns(experiment[2]))

        rmse = []
        smape = []
        u = []
        times = []

        data_columns = analytical_data_columns(experiment[2])

        for b in sorted(bests.keys()):
            if check_ignore_list(b, ignore):
                continue

            if b not in models:
                models[b] = {}
                models[b]['rmse'] = []
                models[b]['smape'] = []
                models[b]['u'] = []
                models[b]['times'] = []

            if b not in mdl:
                mdl[b] = {}
                mdl[b]['rmse'] = []
                mdl[b]['smape'] = []
                mdl[b]['u'] = []
                mdl[b]['times'] = []

            best = bests[b]
            tmp = dat_ana[(dat_ana.Model == best["Model"]) & (dat_ana.Order == best["Order"])
                    & (dat_ana.Scheme == best["Scheme"]) & (dat_ana.Partitions == best["Partitions"])]
            tmpl = extract_measure(tmp,'RMSE',data_columns)
            mdl[b]['rmse'].extend( tmpl )
            rmse.extend( tmpl )
            tmpl = extract_measure(tmp, 'SMAPE', data_columns)
            mdl[b]['smape'].extend(tmpl)
            smape.extend(tmpl)
            tmpl = extract_measure(tmp, 'U', data_columns)
            mdl[b]['u'].extend(tmpl)
            u.extend(tmpl)
            tmpl = extract_measure(tmp, 'TIME', data_columns)
            mdl[b]['times'].extend(tmpl)
            times.extend(tmpl)

            models[b]['label'] = check_replace_list(best["Model"] + " " + str(best["Order"]), replace)

        print("GLOBAL")
        rmse_param = scale_params(rmse)
        stats("rmse", rmse)
        smape_param = scale_params(smape)
        stats("smape", smape)
        u_param = scale_params(u)
        stats("u", u)
        times_param = scale_params(times)

        for key in sorted(models.keys()):
            models[key]['rmse'].extend( scale(mdl[key]['rmse'], rmse_param) )
            models[key]['smape'].extend( scale(mdl[key]['smape'], smape_param) )
            models[key]['u'].extend( scale(mdl[key]['u'], u_param) )
            models[key]['times'].extend( scale(mdl[key]['times'], times_param) )

    rmse = []
    smape = []
    u = []
    times = []
    labels = []
    for key in sorted(models.keys()):
        print(key)
        rmse.append(models[key]['rmse'])
        stats("rmse", models[key]['rmse'])
        smape.append(models[key]['smape'])
        stats("smape", models[key]['smape'])
        u.append(models[key]['u'])
        stats("u", models[key]['u'])
        times.append(models[key]['times'])
        labels.append(models[key]['label'])

    axes[0].boxplot(rmse, labels=labels, autorange=True, showmeans=True)
    axes[0].set_title("RMSE")
    axes[1].boxplot(smape, labels=labels, autorange=True, showmeans=True)
    axes[1].set_title("SMAPE")
    axes[2].boxplot(u, labels=labels, autorange=True, showmeans=True)
    axes[2].set_title("U Statistic")

    plt.tight_layout()

    Util.show_and_save_image(fig, file, save)


def plot_dataframe_point(file_synthetic, file_analytic, experiments, tam, save=False, file=None,
                         sort_columns=['UAVG', 'RMSEAVG', 'USTD', 'RMSESTD'],
                         sort_ascend=[1, 1, 1, 1],save_best=False,
                         ignore=None,replace=None):

    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=tam)

    axes[0].set_title('RMSE')
    axes[1].set_title('SMAPE')
    axes[2].set_title('U Statistic')

    dat_syn = pd.read_csv(file_synthetic, sep=";", usecols=point_dataframe_synthetic_columns())

    bests = find_best(dat_syn, sort_columns, sort_ascend)

    dat_ana = pd.read_csv(file_analytic, sep=";", usecols=point_dataframe_analytic_columns(experiments))

    data_columns = analytical_data_columns(experiments)

    if save_best:
        dat = pd.DataFrame.from_dict(bests, orient='index')
        dat.to_csv(Util.uniquefilename(file_synthetic.replace("synthetic","best")), sep=";", index=False)

    rmse = []
    smape = []
    u = []
    times = []
    labels = []

    for b in sorted(bests.keys()):
        if check_ignore_list(b, ignore):
            continue

        best = bests[b]
        tmp = dat_ana[(dat_ana.Model == best["Model"]) & (dat_ana.Order == best["Order"])
                & (dat_ana.Scheme == best["Scheme"]) & (dat_ana.Partitions == best["Partitions"])]
        rmse.append( extract_measure(tmp,'RMSE',data_columns) )
        smape.append(extract_measure(tmp, 'SMAPE', data_columns))
        u.append(extract_measure(tmp, 'U', data_columns))
        times.append(extract_measure(tmp, 'TIME', data_columns))

        labels.append(check_replace_list(best["Model"] + " " + str(best["Order"]),replace))

    axes[0].boxplot(rmse, labels=labels, autorange=True, showmeans=True)
    axes[0].set_title("RMSE")
    axes[1].boxplot(smape, labels=labels, autorange=True, showmeans=True)
    axes[1].set_title("SMAPE")
    axes[2].boxplot(u, labels=labels, autorange=True, showmeans=True)
    axes[2].set_title("U Statistic")

    plt.tight_layout()

    Util.show_and_save_image(fig, file, save)



def check_replace_list(m, replace):
    if replace is not None:
        for r in replace:
            if r[0] in m:
                return r[1]
    return m



def check_ignore_list(b, ignore):
    flag = False
    if ignore is not None:
        for i in ignore:
            if i in b:
                flag = True
    return flag


def save_dataframe_interval(coverage, experiments, file, objs, resolution, save, sharpness, synthetic, times,
                            q05, q25, q75, q95, steps, method):
    ret = []
    if synthetic:
        for k in sorted(objs.keys()):
            mod = []
            mfts = objs[k]
            mod.append(mfts.shortname)
            mod.append(mfts.order)
            l = len(mfts)
            if not mfts.benchmark_only:
                mod.append(mfts.partitioner.name)
                mod.append(mfts.partitioner.partitions)
                mod.append(l)
            else:
                mod.append('-')
                mod.append('-')
                mod.append('-')
            mod.append(steps[k])
            mod.append(method[k])
            mod.append(round(np.nanmean(sharpness[k]), 2))
            mod.append(round(np.nanstd(sharpness[k]), 2))
            mod.append(round(np.nanmean(resolution[k]), 2))
            mod.append(round(np.nanstd(resolution[k]), 2))
            mod.append(round(np.nanmean(coverage[k]), 2))
            mod.append(round(np.nanstd(coverage[k]), 2))
            mod.append(round(np.nanmean(times[k]), 2))
            mod.append(round(np.nanstd(times[k]), 2))
            mod.append(round(np.nanmean(q05[k]), 2))
            mod.append(round(np.nanstd(q05[k]), 2))
            mod.append(round(np.nanmean(q25[k]), 2))
            mod.append(round(np.nanstd(q25[k]), 2))
            mod.append(round(np.nanmean(q75[k]), 2))
            mod.append(round(np.nanstd(q75[k]), 2))
            mod.append(round(np.nanmean(q95[k]), 2))
            mod.append(round(np.nanstd(q95[k]), 2))
            mod.append(l)
            ret.append(mod)

        columns = interval_dataframe_synthetic_columns()
    else:
        for k in sorted(objs.keys()):
            try:
                mfts = objs[k]
                n = mfts.shortname
                o = mfts.order
                if not mfts.benchmark_only:
                    s = mfts.partitioner.name
                    p = mfts.partitioner.partitions
                    l = len(mfts)
                else:
                    s = '-'
                    p = '-'
                    l = '-'
                st = steps[k]
                mt = method[k]
                tmp = [n, o, s, p, l, st, mt, 'Sharpness']
                tmp.extend(sharpness[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'Resolution']
                tmp.extend(resolution[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'Coverage']
                tmp.extend(coverage[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'TIME']
                tmp.extend(times[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'Q05']
                tmp.extend(q05[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'Q25']
                tmp.extend(q25[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'Q75']
                tmp.extend(q75[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'Q95']
                tmp.extend(q95[k])
                ret.append(deepcopy(tmp))
            except Exception as ex:
                print("Erro ao salvar ", k)
                print("Exceção ", ex)
        columns = interval_dataframe_analytic_columns(experiments)
    dat = pd.DataFrame(ret, columns=columns)
    if save: dat.to_csv(Util.uniquefilename(file), sep=";")
    return dat


def interval_dataframe_analytic_columns(experiments):
    columns = [str(k) for k in np.arange(0, experiments)]
    columns.insert(0, "Model")
    columns.insert(1, "Order")
    columns.insert(2, "Scheme")
    columns.insert(3, "Partitions")
    columns.insert(4, "Size")
    columns.insert(5, "Steps")
    columns.insert(6, "Method")
    columns.insert(7, "Measure")
    return columns



def interval_dataframe_synthetic_columns():
    columns = ["Model", "Order", "Scheme", "Partitions","SIZE", "Steps","Method" "SHARPAVG", "SHARPSTD", "RESAVG", "RESSTD", "COVAVG",
               "COVSTD", "TIMEAVG", "TIMESTD", "Q05AVG", "Q05STD", "Q25AVG", "Q25STD", "Q75AVG", "Q75STD", "Q95AVG", "Q95STD"]
    return columns


def cast_dataframe_to_synthetic_interval(df, data_columns):
    sharpness = extract_measure(df, 'Sharpness', data_columns)
    resolution = extract_measure(df, 'Resolution', data_columns)
    coverage = extract_measure(df, 'Coverage', data_columns)
    times = extract_measure(df, 'TIME', data_columns)
    q05 = extract_measure(df, 'Q05', data_columns)
    q25 = extract_measure(df, 'Q25', data_columns)
    q75 = extract_measure(df, 'Q75', data_columns)
    q95 = extract_measure(df, 'Q95', data_columns)
    ret = []
    ret.append(np.round(np.nanmean(sharpness), 2))
    ret.append(np.round(np.nanstd(sharpness), 2))
    ret.append(np.round(np.nanmean(resolution), 2))
    ret.append(np.round(np.nanstd(resolution), 2))
    ret.append(np.round(np.nanmean(coverage), 2))
    ret.append(np.round(np.nanstd(coverage), 2))
    ret.append(np.round(np.nanmean(times), 4))
    ret.append(np.round(np.nanstd(times), 4))
    ret.append(np.round(np.nanmean(q05), 4))
    ret.append(np.round(np.nanstd(q05), 4))
    ret.append(np.round(np.nanmean(q25), 4))
    ret.append(np.round(np.nanstd(q25), 4))
    ret.append(np.round(np.nanmean(q75), 4))
    ret.append(np.round(np.nanstd(q75), 4))
    ret.append(np.round(np.nanmean(q95), 4))
    ret.append(np.round(np.nanstd(q95), 4))
    return ret




def unified_scaled_interval(experiments, tam, save=False, file=None,
                            sort_columns=['COVAVG', 'SHARPAVG', 'COVSTD', 'SHARPSTD'],
                            sort_ascend=[True, False, True, True],save_best=False,
                            ignore=None, replace=None):
    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=tam)

    axes[0].set_title('Sharpness')
    axes[1].set_title('Resolution')
    axes[2].set_title('Coverage')

    models = {}

    for experiment in experiments:

        mdl = {}

        dat_syn = pd.read_csv(experiment[0], sep=";", usecols=interval_dataframe_synthetic_columns())

        bests = find_best(dat_syn, sort_columns, sort_ascend)

        dat_ana = pd.read_csv(experiment[1], sep=";", usecols=interval_dataframe_analytic_columns(experiment[2]))

        sharpness = []
        resolution = []
        coverage = []
        times = []

        data_columns = analytical_data_columns(experiment[2])

        for b in sorted(bests.keys()):
            if check_ignore_list(b, ignore):
                continue

            if b not in models:
                models[b] = {}
                models[b]['sharpness'] = []
                models[b]['resolution'] = []
                models[b]['coverage'] = []
                models[b]['times'] = []

            if b not in mdl:
                mdl[b] = {}
                mdl[b]['sharpness'] = []
                mdl[b]['resolution'] = []
                mdl[b]['coverage'] = []
                mdl[b]['times'] = []

            best = bests[b]
            print(best)
            tmp = dat_ana[(dat_ana.Model == best["Model"]) & (dat_ana.Order == best["Order"])
                          & (dat_ana.Scheme == best["Scheme"]) & (dat_ana.Partitions == best["Partitions"])]
            tmpl = extract_measure(tmp, 'Sharpness', data_columns)
            mdl[b]['sharpness'].extend(tmpl)
            sharpness.extend(tmpl)
            tmpl = extract_measure(tmp, 'Resolution', data_columns)
            mdl[b]['resolution'].extend(tmpl)
            resolution.extend(tmpl)
            tmpl = extract_measure(tmp, 'Coverage', data_columns)
            mdl[b]['coverage'].extend(tmpl)
            coverage.extend(tmpl)
            tmpl = extract_measure(tmp, 'TIME', data_columns)
            mdl[b]['times'].extend(tmpl)
            times.extend(tmpl)

            models[b]['label'] = check_replace_list(best["Model"] + " " + str(best["Order"]), replace)

        sharpness_param = scale_params(sharpness)
        resolution_param = scale_params(resolution)
        coverage_param = scale_params(coverage)
        times_param = scale_params(times)

        for key in sorted(models.keys()):
            models[key]['sharpness'].extend(scale(mdl[key]['sharpness'], sharpness_param))
            models[key]['resolution'].extend(scale(mdl[key]['resolution'], resolution_param))
            models[key]['coverage'].extend(scale(mdl[key]['coverage'], coverage_param))
            models[key]['times'].extend(scale(mdl[key]['times'], times_param))

    sharpness = []
    resolution = []
    coverage = []
    times = []
    labels = []
    for key in sorted(models.keys()):
        sharpness.append(models[key]['sharpness'])
        resolution.append(models[key]['resolution'])
        coverage.append(models[key]['coverage'])
        times.append(models[key]['times'])
        labels.append(models[key]['label'])

    axes[0].boxplot(sharpness, labels=labels, autorange=True, showmeans=True)
    axes[1].boxplot(resolution, labels=labels, autorange=True, showmeans=True)
    axes[2].boxplot(coverage, labels=labels, autorange=True, showmeans=True)

    plt.tight_layout()

    Util.show_and_save_image(fig, file, save)



def plot_dataframe_interval(file_synthetic, file_analytic, experiments, tam, save=False, file=None,
                            sort_columns=['COVAVG', 'SHARPAVG', 'COVSTD', 'SHARPSTD'],
                            sort_ascend=[True, False, True, True],save_best=False,
                            ignore=None, replace=None):

    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=tam)

    axes[0].set_title('Sharpness')
    axes[1].set_title('Resolution')
    axes[2].set_title('Coverage')

    dat_syn = pd.read_csv(file_synthetic, sep=";", usecols=interval_dataframe_synthetic_columns())

    bests = find_best(dat_syn, sort_columns, sort_ascend)

    dat_ana = pd.read_csv(file_analytic, sep=";", usecols=interval_dataframe_analytic_columns(experiments))

    data_columns = analytical_data_columns(experiments)

    if save_best:
        dat = pd.DataFrame.from_dict(bests, orient='index')
        dat.to_csv(Util.uniquefilename(file_synthetic.replace("synthetic","best")), sep=";", index=False)

    sharpness = []
    resolution = []
    coverage = []
    times = []
    labels = []
    bounds_shp = []

    for b in sorted(bests.keys()):
        if check_ignore_list(b, ignore):
            continue
        best = bests[b]
        df = dat_ana[(dat_ana.Model == best["Model"]) & (dat_ana.Order == best["Order"])
                & (dat_ana.Scheme == best["Scheme"]) & (dat_ana.Partitions == best["Partitions"])]
        sharpness.append( extract_measure(df,'Sharpness',data_columns) )
        resolution.append(extract_measure(df, 'Resolution', data_columns))
        coverage.append(extract_measure(df, 'Coverage', data_columns))
        times.append(extract_measure(df, 'TIME', data_columns))
        labels.append(check_replace_list(best["Model"] + " " + str(best["Order"]), replace))

    axes[0].boxplot(sharpness, labels=labels, autorange=True, showmeans=True)
    axes[0].set_title("Sharpness")
    axes[1].boxplot(resolution, labels=labels, autorange=True, showmeans=True)
    axes[1].set_title("Resolution")
    axes[2].boxplot(coverage, labels=labels, autorange=True, showmeans=True)
    axes[2].set_title("Coverage")
    axes[2].set_ylim([0, 1.1])

    plt.tight_layout()

    Util.show_and_save_image(fig, file, save)



def unified_scaled_interval_pinball(experiments, tam, save=False, file=None,
                                    sort_columns=['COVAVG','SHARPAVG','COVSTD','SHARPSTD'],
                                    sort_ascend=[True, False, True, True], save_best=False,
                                    ignore=None, replace=None):
    fig, axes = plt.subplots(nrows=1, ncols=4, figsize=tam)
    axes[0].set_title(r'$\tau=0.05$')
    axes[1].set_title(r'$\tau=0.25$')
    axes[2].set_title(r'$\tau=0.75$')
    axes[3].set_title(r'$\tau=0.95$')
    models = {}

    for experiment in experiments:

        mdl = {}

        dat_syn = pd.read_csv(experiment[0], sep=";", usecols=interval_dataframe_synthetic_columns())

        bests = find_best(dat_syn, sort_columns, sort_ascend)

        dat_ana = pd.read_csv(experiment[1], sep=";", usecols=interval_dataframe_analytic_columns(experiment[2]))

        q05	= []
        q25 = []
        q75 = []
        q95 = []

        data_columns = analytical_data_columns(experiment[2])

        for b in sorted(bests.keys()):
            if check_ignore_list(b, ignore):
                continue

            if b not in models:
                models[b] = {}
                models[b]['q05'] = []
                models[b]['q25'] = []
                models[b]['q75'] = []
                models[b]['q95'] = []

            if b not in mdl:
                mdl[b] = {}
                mdl[b]['q05'] = []
                mdl[b]['q25'] = []
                mdl[b]['q75'] = []
                mdl[b]['q95'] = []

            best = bests[b]
            print(best)
            tmp = dat_ana[(dat_ana.Model == best["Model"]) & (dat_ana.Order == best["Order"])
                          & (dat_ana.Scheme == best["Scheme"]) & (dat_ana.Partitions == best["Partitions"])]
            tmpl = extract_measure(tmp, 'Q05', data_columns)
            mdl[b]['q05'].extend(tmpl)
            q05.extend(tmpl)
            tmpl = extract_measure(tmp, 'Q25', data_columns)
            mdl[b]['q25'].extend(tmpl)
            q25.extend(tmpl)
            tmpl = extract_measure(tmp, 'Q75', data_columns)
            mdl[b]['q75'].extend(tmpl)
            q75.extend(tmpl)
            tmpl = extract_measure(tmp, 'Q95', data_columns)
            mdl[b]['q95'].extend(tmpl)
            q95.extend(tmpl)

            models[b]['label'] = check_replace_list(best["Model"] + " " + str(best["Order"]), replace)

        q05_param = scale_params(q05)
        q25_param = scale_params(q25)
        q75_param = scale_params(q75)
        q95_param = scale_params(q95)

        for key in sorted(models.keys()):
            models[key]['q05'].extend(scale(mdl[key]['q05'], q05_param))
            models[key]['q25'].extend(scale(mdl[key]['q25'], q25_param))
            models[key]['q75'].extend(scale(mdl[key]['q75'], q75_param))
            models[key]['q95'].extend(scale(mdl[key]['q95'], q95_param))

    q05 = []
    q25 = []
    q75 = []
    q95 = []
    labels = []
    for key in sorted(models.keys()):
        q05.append(models[key]['q05'])
        q25.append(models[key]['q25'])
        q75.append(models[key]['q75'])
        q95.append(models[key]['q95'])
        labels.append(models[key]['label'])

    axes[0].boxplot(q05, labels=labels, vert=False, autorange=True, showmeans=True)
    axes[1].boxplot(q25, labels=labels, vert=False, autorange=True, showmeans=True)
    axes[2].boxplot(q75, labels=labels, vert=False, autorange=True, showmeans=True)
    axes[3].boxplot(q95, labels=labels, vert=False, autorange=True, showmeans=True)

    plt.tight_layout()

    Util.show_and_save_image(fig, file, save)



def plot_dataframe_interval_pinball(file_synthetic, file_analytic, experiments, tam, save=False, file=None,
                                    sort_columns=['COVAVG','SHARPAVG','COVSTD','SHARPSTD'],
                                    sort_ascend=[True, False, True, True], save_best=False,
                                    ignore=None, replace=None):

    fig, axes = plt.subplots(nrows=1, ncols=4, figsize=tam)
    axes[0].set_title(r'$\tau=0.05$')
    axes[1].set_title(r'$\tau=0.25$')
    axes[2].set_title(r'$\tau=0.75$')
    axes[3].set_title(r'$\tau=0.95$')

    dat_syn = pd.read_csv(file_synthetic, sep=";", usecols=interval_dataframe_synthetic_columns())

    bests = find_best(dat_syn, sort_columns, sort_ascend)

    dat_ana = pd.read_csv(file_analytic, sep=";", usecols=interval_dataframe_analytic_columns(experiments))

    data_columns = analytical_data_columns(experiments)

    if save_best:
        dat = pd.DataFrame.from_dict(bests, orient='index')
        dat.to_csv(Util.uniquefilename(file_synthetic.replace("synthetic","best")), sep=";", index=False)

    q05 = []
    q25 = []
    q75 = []
    q95 = []
    labels = []

    for b in sorted(bests.keys()):
        if check_ignore_list(b, ignore):
            continue
        best = bests[b]
        df = dat_ana[(dat_ana.Model == best["Model"]) & (dat_ana.Order == best["Order"])
                & (dat_ana.Scheme == best["Scheme"]) & (dat_ana.Partitions == best["Partitions"])]
        q05.append(extract_measure(df, 'Q05', data_columns))
        q25.append(extract_measure(df, 'Q25', data_columns))
        q75.append(extract_measure(df, 'Q75', data_columns))
        q95.append(extract_measure(df, 'Q95', data_columns))
        labels.append(check_replace_list(best["Model"] + " " + str(best["Order"]), replace))

    axes[0].boxplot(q05, labels=labels, vert=False, autorange=True, showmeans=True)
    axes[1].boxplot(q25, labels=labels, vert=False, autorange=True, showmeans=True)
    axes[2].boxplot(q75, labels=labels, vert=False, autorange=True, showmeans=True)
    axes[3].boxplot(q95, labels=labels, vert=False, autorange=True, showmeans=True)

    plt.tight_layout()

    Util.show_and_save_image(fig, file, save)


def save_dataframe_probabilistic(experiments, file, objs, crps, times, save, synthetic, steps, method):
    """
    Save benchmark results for m-step ahead probabilistic forecasters 
    :param experiments: 
    :param file: 
    :param objs: 
    :param crps_interval: 
    :param crps_distr: 
    :param times: 
    :param times2: 
    :param save: 
    :param synthetic: 
    :return: 
    """
    ret = []

    if synthetic:

        for k in sorted(objs.keys()):
            try:
                ret = []
                for k in sorted(objs.keys()):
                    try:
                        mod = []
                        mfts = objs[k]
                        mod.append(mfts.shortname)
                        mod.append(mfts.order)
                        if not mfts.benchmark_only:
                            mod.append(mfts.partitioner.name)
                            mod.append(mfts.partitioner.partitions)
                            mod.append(len(mfts))
                        else:
                            mod.append('-')
                            mod.append('-')
                            mod.append('-')
                        mod.append(steps[k])
                        mod.append(method[k])
                        mod.append(np.round(np.nanmean(crps[k]), 2))
                        mod.append(np.round(np.nanstd(crps[k]), 2))
                        mod.append(np.round(np.nanmean(times[k]), 4))
                        mod.append(np.round(np.nanstd(times[k]), 4))
                        ret.append(mod)
                    except Exception as e:
                        print('Erro: %s' % e)
            except Exception as ex:
                print("Erro ao salvar ", k)
                print("Exceção ", ex)

        columns = probabilistic_dataframe_synthetic_columns()
    else:
        for k in sorted(objs.keys()):
            try:
                mfts = objs[k]
                n = mfts.shortname
                o = mfts.order
                if not mfts.benchmark_only:
                    s = mfts.partitioner.name
                    p = mfts.partitioner.partitions
                    l = len(mfts)
                else:
                    s = '-'
                    p = '-'
                    l = '-'
                st = steps[k]
                mt = method[k]
                tmp = [n, o, s, p, l, st, mt, 'CRPS']
                tmp.extend(crps[k])
                ret.append(deepcopy(tmp))
                tmp = [n, o, s, p, l, st, mt, 'TIME']
                tmp.extend(times[k])
                ret.append(deepcopy(tmp))
            except Exception as ex:
                print("Erro ao salvar ", k)
                print("Exceção ", ex)
        columns = probabilistic_dataframe_analytic_columns(experiments)
    dat = pd.DataFrame(ret, columns=columns)
    if save: dat.to_csv(Util.uniquefilename(file), sep=";")
    return dat


def probabilistic_dataframe_analytic_columns(experiments):
    columns = [str(k) for k in np.arange(0, experiments)]
    columns.insert(0, "Model")
    columns.insert(1, "Order")
    columns.insert(2, "Scheme")
    columns.insert(3, "Partitions")
    columns.insert(4, "Size")
    columns.insert(5, "Steps")
    columns.insert(6, "Method")
    columns.insert(7, "Measure")
    return columns


def probabilistic_dataframe_synthetic_columns():
    columns = ["Model", "Order", "Scheme", "Partitions","Size", "Steps", "Method", "CRPSAVG", "CRPSSTD",
               "TIMEAVG", "TIMESTD"]
    return columns


def cast_dataframe_to_synthetic_probabilistic(df, data_columns):
    crps1 = extract_measure(df, 'CRPS', data_columns)
    times1 = extract_measure(df, 'TIME', data_columns)
    ret = []
    ret.append(np.round(np.nanmean(crps1), 2))
    ret.append(np.round(np.nanstd(crps1), 2))
    ret.append(np.round(np.nanmean(times1), 2))
    ret.append(np.round(np.nanstd(times1), 2))
    return ret


def unified_scaled_probabilistic(experiments, tam, save=False, file=None,
                                 sort_columns=['CRPSAVG', 'CRPSSTD'],
                                 sort_ascend=[True, True], save_best=False,
                                 ignore=None, replace=None):
    fig, axes = plt.subplots(nrows=1, ncols=1, figsize=tam)

    axes.set_title('CRPS')
    #axes[1].set_title('CRPS Distribution Ahead')

    models = {}

    for experiment in experiments:

        print(experiment)

        mdl = {}

        dat_syn = pd.read_csv(experiment[0], sep=";", usecols=probabilistic_dataframe_synthetic_columns())

        bests = find_best(dat_syn, sort_columns, sort_ascend)

        dat_ana = pd.read_csv(experiment[1], sep=";", usecols=probabilistic_dataframe_analytic_columns(experiment[2]))

        crps1 = []
        crps2 = []

        data_columns = analytical_data_columns(experiment[2])

        for b in sorted(bests.keys()):
            if check_ignore_list(b, ignore):
                continue

            if b not in models:
                models[b] = {}
                models[b]['crps1'] = []
                models[b]['crps2'] = []

            if b not in mdl:
                mdl[b] = {}
                mdl[b]['crps1'] = []
                mdl[b]['crps2'] = []

            best = bests[b]

            print(best)

            tmp = dat_ana[(dat_ana.Model == best["Model"]) & (dat_ana.Order == best["Order"])
                          & (dat_ana.Scheme == best["Scheme"]) & (dat_ana.Partitions == best["Partitions"])]
            tmpl = extract_measure(tmp, 'CRPS_Interval', data_columns)
            mdl[b]['crps1'].extend(tmpl)
            crps1.extend(tmpl)
            tmpl = extract_measure(tmp, 'CRPS_Distribution', data_columns)
            mdl[b]['crps2'].extend(tmpl)
            crps2.extend(tmpl)

            models[b]['label'] = check_replace_list(best["Model"] + " " + str(best["Order"]), replace)

        crps1_param = scale_params(crps1)
        crps2_param = scale_params(crps2)

        for key in sorted(mdl.keys()):
            print(key)
            models[key]['crps1'].extend(scale(mdl[key]['crps1'], crps1_param))
            models[key]['crps2'].extend(scale(mdl[key]['crps2'], crps2_param))

    crps1 = []
    crps2 = []
    labels = []
    for key in sorted(models.keys()):
        crps1.append(models[key]['crps1'])
        crps2.append(models[key]['crps2'])
        labels.append(models[key]['label'])

    axes[0].boxplot(crps1, labels=labels, autorange=True, showmeans=True)
    axes[1].boxplot(crps2, labels=labels, autorange=True, showmeans=True)

    plt.tight_layout()

    Util.show_and_save_image(fig, file, save)



def plot_dataframe_probabilistic(file_synthetic, file_analytic, experiments, tam, save=False, file=None,
                                 sort_columns=['CRPS1AVG', 'CRPS2AVG', 'CRPS1STD', 'CRPS2STD'],
                                 sort_ascend=[True, True, True, True], save_best=False,
                                 ignore=None, replace=None):

    fig, axes = plt.subplots(nrows=2, ncols=1, figsize=tam)

    axes[0].set_title('CRPS')
    axes[1].set_title('CRPS')

    dat_syn = pd.read_csv(file_synthetic, sep=";", usecols=probabilistic_dataframe_synthetic_columns())

    bests = find_best(dat_syn, sort_columns, sort_ascend)

    dat_ana = pd.read_csv(file_analytic, sep=";", usecols=probabilistic_dataframe_analytic_columns(experiments))

    data_columns = analytical_data_columns(experiments)

    if save_best:
        dat = pd.DataFrame.from_dict(bests, orient='index')
        dat.to_csv(Util.uniquefilename(file_synthetic.replace("synthetic","best")), sep=";", index=False)

    crps1 = []
    crps2 = []
    labels = []

    for b in sorted(bests.keys()):
        if check_ignore_list(b, ignore):
            continue
        best = bests[b]
        df = dat_ana[(dat_ana.Model == best["Model"]) & (dat_ana.Order == best["Order"])
                & (dat_ana.Scheme == best["Scheme"]) & (dat_ana.Partitions == best["Partitions"])]
        crps1.append( extract_measure(df,'CRPS_Interval',data_columns) )
        crps2.append(extract_measure(df, 'CRPS_Distribution', data_columns))
        labels.append(check_replace_list(best["Model"] + " " + str(best["Order"]), replace))

    axes[0].boxplot(crps1, labels=labels, autorange=True, showmeans=True)
    axes[1].boxplot(crps2, labels=labels, autorange=True, showmeans=True)

    plt.tight_layout()
    Util.show_and_save_image(fig, file, save)

