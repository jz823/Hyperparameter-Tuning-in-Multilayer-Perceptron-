# -*- coding: utf-8 -*-
"""data_pipline_v2.1.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1bbTyUaaRzkUe7EUuAIsP64CvRknHr7OW
"""

import keras_tuner as kt
import tensorflow_addons as tfa
import datetime as dt
import re

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import tensorflow as tf
from tensorflow import keras
from keras.models import Sequential
from keras.layers import Input
from keras.layers import Dense

import os
import gc

BASE_DIR = r'F:\ML\\'
MODEL_DIR = BASE_DIR + 'Model_saves\\'
DATA_DIR = BASE_DIR + 'DailyPrediction\\'

def Roos_sq(ret,ret_hat):
    """
    calculate out of sample R^2
    """
    return 1 - (((ret - ret_hat)**2).sum())/((ret**2).sum())


def get_data_file(filename):
    """ 
    load a dataframe given file name
    """
    df = pd.DataFrame()
    for file_path in filename:
        df_add = pd.read_parquet(file_path)
    df = pd.concat([df,df_add],axis=0)
    return df

def get_filenames_for_period(period):
    filenames = []
    for date in period:
        filenames.append(str(date.year)+'_'+str(date.month)+'.parquet.gzip')
    return filenames


def get_data_filenames(data_dir, start_date=dt.datetime.strptime('1973_1_31','%Y_%m_%d'), n_train=3, n_valid=1, n_test=1):          # CHANGED
    # I modify this function a little bit
    # change start_date string, the default argument, to the form as in the filename
    # change start_date, the date, to the type of datetime  
    
    end_date = start_date + pd.offsets.MonthEnd(n_train + n_valid + n_test)
    assert os.path.exists(data_dir+str(end_date.year)+'_'+str(end_date.month)+'.parquet.gzip')

    train_period = []
    valid_period = []
    test_period = []
    for i in range(n_train):
        train_period.append(start_date+pd.offsets.MonthEnd(i))
    for i in range(n_train, n_train+n_valid):
        valid_period.append(start_date+pd.offsets.MonthEnd(i))
    for i in range(n_train+n_valid, n_train+n_valid+n_test):
        test_period.append(start_date+pd.offsets.MonthEnd(i))

    train_files = [data_dir + f for f in get_filenames_for_period(train_period)]
    valid_files = [data_dir + f for f in get_filenames_for_period(valid_period)]
    test_files = [data_dir + f for f in get_filenames_for_period(test_period)]

    return train_files, valid_files, test_files

def generator(filename, batch_size):
    """
    Generator function for reading data from a parquet batch by batch
    """
    try:
        filename = filename.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        pass
    
    x = pd.read_parquet(filename, columns=COL_X).values.astype('float16')
    y = pd.read_parquet(filename, columns=COL_Y).values.astype('float32')

    assert len(x) == len(y)
    
    cursor = 0
    
    while cursor < len(x):
        if cursor + batch_size - 1 < len(x):
            yield x[cursor:cursor + batch_size], y[cursor:cursor + batch_size]
        else:
            yield x[cursor:], y[cursor:]
        cursor += batch_size

# model = Sequential()
# model.add(Input(shape=(len(COL_X),)))
# model.add(Dense(3, activation='relu'))
# model.add(Dense(1, activation='relu'))

# model.compile(optimizer=keras.optimizers.Adam(), loss=keras.losses.MeanAbsoluteError())

# model.summary()

#model.fit(train_gen, epochs=1, batch_size=128, validation_data=valid_gen)

def build_model(hp):
    # choose learning rate from
    lr = [0.1]#,0.01]                                                         # !!!

    # regularization parameter
    l1_wt=1e-1

    # choose numebr of layers from
    layers = [3,4]                                                            # !!!

    # list of functions, mapping the number of layers to the number of units each layer
    layer_units_maps = [lambda n:[2**(n-i+1) for i in range(1,n+1)],
                      lambda n:[int(np.mean([2**(n-i+1) for i in range(1,n+1)]))]*n]      # !!!

    # dict: {the number of layers: a list of unit number each layer}
    units_dict = dict()
    for n in layers:
        units_dict[n] = []
        for map in layer_units_maps:
            units_dict[n].append(map(n))
    # units_dict = {3:[[8,4,2],[4,4,4]],
    #               4:[[16,8,4,2],[7,7,7]]}
    
    # choose the numebr of layers
    n_layers = hp.Choice(name='n_layers',values=layers)

    # choose the activation function from
    act_func = hp.Choice(name='act_func',values=['relu','sigmoid'])             # !!!
    
    tf.keras.utils.set_random_seed(seed=1998)
    model = keras.Sequential()

    for layer in range(n_layers):
        if layer == 0:
            # while defining the first layer, choose pyramid or contant units for the layers
            # 0 for pyramid, 1 for constant
            units = hp.Choice(name='units_dist',values=list(range(len(layer_units_maps))))
            model.add(Dense(units=units_dict[n_layers][units][layer],
                              activation=act_func,
                              kernel_initializer='he_uniform',
                              kernel_regularizer=keras.regularizers.L1(l1_wt))
            )
        else:
            model.add(Dense(units=units_dict[n_layers][units][layer],
                              activation=act_func,
                              kernel_initializer='he_uniform',
                              kernel_regularizer=keras.regularizers.L1(l1_wt))
            )
    model.add(Dense(units=1,kernel_regularizer=keras.regularizers.L1(l1_wt)),
               )

    # Choose the learning rate
    lr = hp.Choice('learning_rate', values=lr)
    #print(lr,n_layers,units,act_func)
    # compile the model
    model.compile(loss='mse',
                  optimizer=keras.optimizers.Adam(lr),
                  metrics=tfa.metrics.r_square.RSquare())
    
    return model

def opt_model_output(build_model,train_gen,valid_gen,test_gen,train_files,valid_files,test_files,df_record,n_train,n_valid,n_test):
    model_name = re.search(r'\d{4}_\d+',train_files[0]).group()+'_{}{}{}'.format(n_train,n_valid,n_test)
    stop_early = keras.callbacks.EarlyStopping(monitor='val_loss', patience=5,verbose=0)
    tuner = kt.BayesianOptimization(hypermodel=build_model,
                                    max_trials=2,                         #!!!
                                    objective='val_loss',
                                    overwrite=True,
                                    directory=MODEL_DIR,                  # NEW
                                    project_name=model_name)

    results = tuner.search(train_gen, 
                            validation_data = valid_gen,
                            callbacks=[stop_early])


    # take the best model
    best_hps = tuner.get_best_hyperparameters()[0]
    model = tuner.hypermodel.build(best_hps)
    stop_early = keras.callbacks.EarlyStopping(monitor='val_loss', patience=5,verbose=0)

    # add hot-start
    print('hot_start_begin')
    history = model.fit(train_gen, 
                        validation_data = valid_gen,
                        callbacks=[stop_early],epochs=1)            #!!!
    print('hot_start_end')

    best_hps = tuner.get_best_hyperparameters()[0]
    extract_dt = lambda filename: dt.datetime.strptime(re.search(r'\d{4}_\d+',filename).group(),'%Y_%m')
    
    #############################
    # save the modelF
    if not os.path.isdir(MODEL_DIR):
        os.mkdir(MODEL_DIR)
    model.save(MODEL_DIR + model_name +'.h5')                        # NEW
    #############################
    
    # document training details
    print("Loading df")
    train_df = get_data_file(train_files)
    test_df = get_data_file(test_files)

    print("documenting_start")
    traing_start = extract_dt(train_files[0])
    train_end = extract_dt(train_files[-1]) + pd.offsets.MonthEnd(1)
    valid_end = extract_dt(valid_files[-1]) + pd.offsets.MonthEnd(1)
    test_end = extract_dt(test_files[-1]) + pd.offsets.MonthEnd(1)
    print('date_ok')
    in_sample_R2 = None #Roos_sq(train_df[COL_Y[0]],model.predict(train_gen))
    Roos2 = None # Roos_sq(test_df[COL_Y[0]],model.predict(test_gen))
    print('R2_ok')
    number_of_layers = best_hps.get('n_layers')
    layer_structure = best_hps.get('units_dist')
    learning_rate = best_hps.get('learning_rate')
    activation_function = best_hps.get('act_func')

    del train_df
    del test_df
    gc.collect()

    print('constructing_df_record')
    df_add = pd.DataFrame([[traing_start,
                            train_end,
                            valid_end,
                            test_end,
                            in_sample_R2,
                            Roos2,
                            number_of_layers,
                            layer_structure,
                            learning_rate,
                            activation_function]],
                            columns=df_record.columns)
    #print(df_add)
    print('constructing_complete')
    df_record = pd.concat([df_record,df_add],axis=0)
    df_record.to_csv(MODEL_DIR+re.search(r'\d{4}_\d+',train_files[0]).group()+'.csv')   # NEW
    return df_record

    #####################################################
    
    # save the df_record
    # df_record.to_csv(MODEL_DIR+re.search(r'\d{4}_\d+',train_files[0]).group()+'.csv')
    
    #####################################################

# For another user, please change DATA_DIR. If you do not run on colab, delete drive.amount
# There are still some parameters to adjust in the function definitions above

def main():
# define global variabls
    n_train, n_valid, n_test = 1, 1, 1
    GEN_BATCH_SIZE = 2 ** 8
    cur_date = dt.datetime.strptime('1973_1','%Y_%m') + pd.offsets.MonthEnd()
    
    df_sample = pd.read_parquet(DATA_DIR+'1973_1.parquet.gzip')

    global COL_X
    global COL_Y  
    #global df_record

    COL_X = list(df_sample.columns[2:])
    COL_Y = ['excess_ret']
    COL_X.remove(COL_Y[0])
    df_sample.info()
    del df_sample
    # gc.collect()

  # This is a dataframe to record the information of each training
    df_record = pd.DataFrame(columns=['traing_start',
                                'train_end',
                                'valid_end',
                                'test_end',
                                'in_sample_R2',
                                'Roos2',
                                'number_of_layers',
                                'layer_structure',
                                'learning_rate',
                                'activation_function'
                                ])

    while True:
        
        end_of_train = pd.to_datetime('1983_12',format='%Y_%m') + pd.offsets.MonthEnd(-(n_train + n_valid + n_test))
        try:
            if cur_date > dt.datetime.strptime('1973_5','%Y_%m'):
                break
            #####################################################
            # Final version of loop
            # if cur_date <= end_of_train:
            #####################################################

            # if the training record/model file with respect to the cur_date exists 
                # update cur_date to the next training window
                # continue

            #####################################################
            print('Train starts at', cur_date)
            # get the file name of training, validation, testing set for this iteration
            train_files, valid_files, test_files = get_data_filenames(DATA_DIR,cur_date,n_train, n_valid, n_test)

            # get the generator for the training
            train_gen = \
              tf.data.Dataset\
                .from_tensor_slices(train_files)\
              .interleave(
                  lambda filename: tf.data.Dataset.from_generator(
                      generator, 
                      output_signature=(
                          tf.TensorSpec(shape=(None, len(COL_X)), dtype=tf.float16), 
                          tf.TensorSpec(shape=(None, 1), dtype=tf.float32)), 
                      args=(filename, GEN_BATCH_SIZE)), 
                  num_parallel_calls=tf.data.experimental.AUTOTUNE)\
              .prefetch(tf.data.experimental.AUTOTUNE)\
              .shuffle(len(train_files), seed=3141, reshuffle_each_iteration=True)  #!!!!

            valid_gen = \
              tf.data.Dataset\
                .from_tensor_slices(valid_files)\
                .interleave(
                  lambda filename: tf.data.Dataset.from_generator(
                      generator, 
                      output_signature=(
                          tf.TensorSpec(shape=(None, len(COL_X)), dtype=tf.float16), 
                          tf.TensorSpec(shape=(None, 1), dtype=tf.float32)), 
                      args=(filename, GEN_BATCH_SIZE)),  
                  num_parallel_calls=tf.data.experimental.AUTOTUNE)\
              .prefetch(tf.data.experimental.AUTOTUNE)

            test_gen = \
              tf.data.Dataset\
                .from_tensor_slices(test_files)\
              .interleave(
                  lambda filename: tf.data.Dataset.from_generator(
                      generator, 
                      output_signature=(
                          tf.TensorSpec(shape=(None, len(COL_X)), dtype=tf.float16), 
                          tf.TensorSpec(shape=(None, 1), dtype=tf.float32)), 
                      args=(filename, GEN_BATCH_SIZE)), 
                  num_parallel_calls=tf.data.experimental.AUTOTUNE)\
              .prefetch(tf.data.experimental.AUTOTUNE)

            # fit the training, validation and testing sets in the hyperparamter model
            df_record = opt_model_output(build_model,train_gen,valid_gen,test_gen,train_files,valid_files,test_files,df_record,n_train,n_valid,n_test)

            # build the date for the next iteration
            cur_date = cur_date + pd.offsets.MonthEnd(n_test)
        except AssertionError:
            break
    df_record.reset_index(inplace=True)
    print(df_record)

main()

import numpy as np
layers = [4,6,8]
layer_unit_dict = {4:64,6:64,8:64}

def layer_structure(n_layer,m_units):
    const_struc = [m_units]*n_layer
    pyramid_struc = []
    start_units = int(np.log(n_layer*m_units/(2**n_layer-1))/np.log(2))+1
    for i in range(n_layer):
        pyramid_struc.append(start_units*2**i)
    pyramid_struc = pyramid_struc[::-1]
    return const_struc,pyramid_struc

layer_units_maps = [lambda n:layer_structure(n,layer_unit_dict[n])[1],
                      lambda n:layer_structure(n,layer_unit_dict[n])[0]]

units_dict = dict()
for n in layers:
  units_dict[n] = []
  for map in layer_units_maps:
    units_dict[n].append(map(n))

