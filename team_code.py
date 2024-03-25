#!/usr/bin/env python

# Edit this script to add your team's code. Some functions are *required*, but you can edit most parts of the required functions,
# change or remove non-required functions, and add your own functions.

################################################################################
#
# Optional libraries, functions, and variables. You can change or remove them.
#
################################################################################

import joblib
import json
import numpy as np
import os

import wfdb
# from keras import Sequential, layers
from keras import optimizers
from keras.layers import SimpleRNN, Dense
from keras.src.layers import MultiHeadAttention, Reshape
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
import sys

from helper_code import *
from keras.models import load_model
import tensorflow as tf
from keras.models import Sequential, load_model, Model
from keras.layers import Conv1D, MaxPooling1D, Flatten, Dense, Dropout, Input, LayerNormalization
import cloudpickle as pickle
from keras.models import model_from_json


################################################################################
#
# Required functions. Edit these functions to add your code, but do not change the arguments of the functions.
#
################################################################################

# Train your digitization model.

def extract_labels(record):
    raw_signal, _ = wfdb.rdsamp(record)
    num_leads = raw_signal.shape[1]
    num_samples = raw_signal.shape[0]
    all_lead_data = []
    for j in range(num_leads):
        lead_data = raw_signal[:, j]
        all_lead_data.append(lead_data)
    all_lead_data = np.array(all_lead_data)
    return all_lead_data


# 定义Transformer模型
def transformer_encoder(inputs, head_size, num_heads, ff_dim, rate=0.1):
    # Multi-head self-attention mechanism
    x = MultiHeadAttention(
        num_heads=num_heads, key_dim=head_size, dropout=rate
    )(inputs, inputs)
    attention_output = LayerNormalization(epsilon=1e-6)(x + inputs)
    linear_layer = Dense(units=2)(attention_output)
    x = x + linear_layer

    # LayerNormalization
    output = LayerNormalization(epsilon=1e-6)(x)

    # Feed-forward neural network
    # x = Conv1D(filters=ff_dim, kernel_size=1, activation="relu")(attention_output)
    # output = LayerNormalization(epsilon=1e-6)(x + attention_output)
    return output


# 构建Transformer模型
def build_model(input_shape, head_size, num_heads, ff_dim, num_transformer_blocks, mlp_units, dropout_rate):
    inputs = Input(shape=input_shape)
    x = inputs

    # 堆叠多个Transformer encoder blocks
    for _ in range(num_transformer_blocks):
        x = transformer_encoder(x, head_size, num_heads, ff_dim)

    # 全连接层
    x = Flatten()(x)
    for mlp_unit in mlp_units:
        x = Dense(mlp_unit, activation="relu")(x)
        x = Dropout(dropout_rate)(x)
    outputs = Dense(12*1000, activation="sigmoid")(x)  # 假设标签数据的形状是(967, 12, 1000)
    outputs = Reshape((12, 1000))(outputs)  # 将输出转换为（batch, 12, 1000）

    return Model(inputs, outputs)

def train_digitization_model(data_folder, model_folder, verbose):
    # Find data files.
    if verbose:
        print('Training the digitization model...')
        print('Finding the Challenge data...')

    records = find_records(data_folder)
    num_records = len(records)

    if num_records == 0:
        raise FileNotFoundError('No data was provided.')

    # Extract the features and labels.
    if verbose:
        print('Extracting features and labels from the data...')

    features = list()
    labels = list()

    for i in range(num_records):
        if verbose:
            width = len(str(num_records))
            print(f'- {i+1:>{width}}/{num_records}: {records[i]}...')

        record = os.path.join(data_folder, records[i])

        # Extract the features from the image...
        current_features = extract_features(record)
        current_features = current_features.reshape((1, -1))  # (1,2)
        features.append(current_features)

        # 获取标签值
        current_labels = extract_labels(record)   # (12,1000)
        labels.append(current_labels)


    # Train the model.
    if verbose:
        print('Training the model on the data...')

    # This overly simple model uses the mean of these overly simple features as a seed for a random number generator.
    # model = np.mean(features)

    features = np.array(features)
    labels = np.array(labels)

    model = build_model(input_shape=(1, 2), head_size=256, num_heads=4, ff_dim=4, num_transformer_blocks=4,
                        mlp_units=[128, 64], dropout_rate=0.1)

    # 编译模型
    model.compile(optimizer=optimizers.Adam(learning_rate=1e-4), loss="mse")
    model.fit(features, labels, epochs=20, batch_size=32)

    # Create a folder for the model if it does not already exist.
    os.makedirs(model_folder, exist_ok=True)

    # Save the model.
    save_digitization_model(model_folder, model)

    if verbose:
        print('Done.')
        print()

# Train your dx classification model.
def train_dx_model(data_folder, model_folder, verbose):
    # Find data files.
    if verbose:
        print('Training the dx classification model...')
        print('Finding the Challenge data...')

    records = find_records(data_folder)
    num_records = len(records)

    if num_records == 0:
        raise FileNotFoundError('No data was provided.')

    # Extract the features and labels.
    if verbose:
        print('Extracting features and labels from the data...')

    features = list()
    dxs = list()

    for i in range(num_records):
        if verbose:
            width = len(str(num_records))
            print(f'- {i+1:>{width}}/{num_records}: {records[i]}...')

        record = os.path.join(data_folder, records[i])

        # Extract the features from the image, but only if the image has one or more dx classes.
        dx = load_dx(record)
        if dx:
            current_features = extract_features(record)
            features.append(current_features)
            dxs.append(dx)

    if not dxs:
        raise Exception('There are no labels for the data.')

    features = np.vstack(features)
    classes = sorted(set.union(*map(set, dxs)))
    dxs = compute_one_hot_encoding(dxs, classes)   # 标签值 热编码

    # Train the model.
    if verbose:
        print('Training the model on the data...')

    # # Define parameters for random forest classifier and regressor.
    # n_estimators   = 12  # Number of trees in the forest.
    # max_leaf_nodes = 34  # Maximum number of leaf nodes in each tree.
    # random_state   = 56  # Random state; set for reproducibility.
    #
    # # Fit the model.
    # model = RandomForestClassifier(
    #     n_estimators=n_estimators, max_leaf_nodes=max_leaf_nodes, random_state=random_state).fit(features, dxs)


    # 构建模型
    model = Sequential()
    model.add(Dense(64, activation='relu', input_shape=(1, 2)))
    model.add(Dropout(0.5))
    model.add(Dense(64, activation='relu'))
    model.add(Dropout(0.5))
    model.add(Dense(2, activation='softmax'))
    #编译模型
    model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])

    features_3d = features.reshape(features.shape[0], 1, features.shape[1])
    dxs_3d = dxs.reshape(dxs.shape[0], 1, dxs.shape[1])
    # 训练模型
    model.fit(features_3d, dxs_3d, epochs=20, batch_size=32, validation_split=0.2)

    # Create a folder for the model if it does not already exist.
    os.makedirs(model_folder, exist_ok=True)

    # Save the model.
    save_dx_model(model_folder, model, classes)

    if verbose:
        print('Done.')
        print()

# Load your trained digitization model. This function is *required*. You should edit this function to add your code, but do *not*
# change the arguments of this function. If you do not train a digitization model, then you can return None.
# def load_digitization_model(model_folder, verbose):
#     filename = os.path.join(model_folder, 'digitization_model.sav')
#     return joblib.load(filename)
def load_digitization_model(model_folder, verbose):
    filename = os.path.join(model_folder, 'digitization_model.pkl')
    with open(filename, 'rb') as f:
        loaded_model_data = pickle.load(f)
    return loaded_model_data


# Load your trained dx classification model. This function is *required*. You should edit this function to add your code, but do
# *not* change the arguments of this function. If you do not train a dx classification model, then you can return None.
# def load_dx_model(model_folder, verbose):
#     filename = os.path.join(model_folder, 'dx_model.sav')
#     return joblib.load(filename)
def load_dx_model(model_folder, verbose):
    filename = os.path.join(model_folder, 'dx_model.pkl')
    with open(filename, 'rb') as f:
        loaded_model_data = pickle.load(f)
    return loaded_model_data

# Run your trained digitization model. This function is *required*. You should edit this function to add your code, but do *not*
# change the arguments of this function.
def run_digitization_model(digitization_model, record, verbose):
    # model = digitization_model['model']
    model = model_from_json(digitization_model['model'])
    # Extract features.
    features = extract_features(record)

    # Load the dimensions of the signal.
    header_file = get_header_file(record)
    header = load_text(header_file)

    num_samples = get_num_samples(header)    # 样本数 1000
    num_signals = get_num_signals(header)    # 导联数 12


    # For a overly simply minimal working example, generate "random" waveforms.
    seed = int(round(np.mean(features)))
    signal = np.random.default_rng(seed=seed).uniform(low=-1000, high=1000, size=(num_samples, num_signals))
    signal = np.asarray(signal, dtype=np.int16)

    return signal

# Run your trained dx classification model. This function is *required*. You should edit this function to add your code, but do
# *not* change the arguments of this function.
def run_dx_model(dx_model, record, signal, verbose):
    # model = dx_model['model']
    model = model_from_json(dx_model['model'])
    classes = dx_model['classes']

    # Extract features.
    features = extract_features(record)
    features = features.reshape(1, -1)
    features = features.reshape(-1, 1, 2)
    # features = features.reshape(1, features.shape[0], features.shape[1])

    # Get model probabilities.
    # probabilities = model.predict_proba(features)
    probabilities = model.predict(features)
    probabilities = np.asarray(probabilities, dtype=np.float32)[:, 0, 1]

    # Choose the class(es) with the highest probability as the label(s).
    max_probability = np.nanmax(probabilities)
    labels = [classes[i] for i, probability in enumerate(probabilities) if probability == max_probability]

    return labels

################################################################################
#
# Optional functions. You can change or remove these functions and/or add new functions.
#
################################################################################

# Extract features.
def extract_features(record):
    images = load_image(record)
    mean = 0.0
    std = 0.0
    for image in images:
        image = np.asarray(image)
        mean += np.mean(image)
        std += np.std(image)
    return np.array([mean, std])

# Save your trained digitization model.
# def save_digitization_model(model_folder, model):
#     d = {'model': model}
#     filename = os.path.join(model_folder, 'digitization_model.sav')
#     joblib.dump(d, filename, protocol=0)
def save_digitization_model(model_folder, model):
    d = {'model': model.to_json()}
    filename = os.path.join(model_folder, 'digitization_model.pkl')
    with open(filename, 'wb') as f:
        pickle.dump(d, f)

# Save your trained dx classification model.
# def save_dx_model(model_folder, model, classes):
#     d = {'model': model, 'classes': classes}
#     filename = os.path.join(model_folder, 'dx_model.sav')
#     joblib.dump(d, filename, protocol=0)

def save_dx_model(model_folder, model, classes):
    model_data = {'model': model.to_json(), 'classes': classes}
    filename = os.path.join(model_folder, 'dx_model.pkl')
    with open(filename, 'wb') as f:
        pickle.dump(model_data, f)
