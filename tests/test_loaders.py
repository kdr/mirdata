# -*- coding: utf-8 -*-

import importlib
import inspect
from inspect import signature
import io
import os
import requests
import sys
import pytest

import mirdata
from mirdata import track
from tests.test_utils import DEFAULT_DATA_HOME

DATASETS = [importlib.import_module("mirdata.{}".format(d)) for d in mirdata.__all__]
CUSTOM_TEST_TRACKS = {
    'beatles': '0111',
    'dali': '4b196e6c99574dd49ad00d56e132712b',
    'guitarset': '03_BN3-119-G_solo',
    'medley_solos_db': 'd07b1fc0-567d-52c2-fef4-239f31c9d40e',
    'medleydb_melody': 'MusicDelta_Beethoven',
    'rwc_classical': 'RM-C003',
    'rwc_jazz': 'RM-J004',
    'rwc_popular': 'RM-P001',
    'salami': '2',
    'tinysol': 'Fl-ord-C4-mf-N-T14d',
}


def test_cite():
    for dataset in DATASETS:
        text_trap = io.StringIO()
        sys.stdout = text_trap
        dataset.cite()
        sys.stdout = sys.__stdout__


KNOWN_ISSUES = {}  # key is module, value is REMOTE key


def test_download(mocker):
    for dataset in DATASETS:
        dataset_name = dataset.__name__.split('.')[1]
        print(dataset_name)

        # test parameters & defaults
        assert hasattr(dataset, 'download')
        assert hasattr(dataset.download, '__call__')
        params = signature(dataset.download).parameters
        assert 'data_home' in params
        assert params['data_home'].default is None

        # if there are no remotes, make sure partial_download,
        # force_overwrite, and cleanup are not parameters
        if not hasattr(dataset, 'REMOTES'):
            assert 'partial_download' not in params
            assert 'force_overwrite' not in params
            assert 'cleanup' not in params
        # if there are remotes, make sure force_overwrite is specified and
        # the default is False
        else:
            assert 'force_overwrite' in params
            assert params['force_overwrite'].default is False

            # if there are remotes but only one item, make sure partial_download
            # is not a parameter
            if len(dataset.REMOTES) == 1:
                assert 'partial_download' not in params
            # if there is more than one item in remotes, make sure partial_download
            # is a parameter and the default is None
            else:
                assert 'partial_download' in params
                assert params['partial_download'].default is None

            extensions = [
                os.path.splitext(r.filename)[-1] for r in dataset.REMOTES.values()
            ]
            # if there are any zip or tar files to download, make sure cleanup
            # is a parameter and its default is True
            if any([e == '.zip' or e == '.gz' for e in extensions]):
                assert 'cleanup' in params
                assert params['cleanup'].default is True
            # if there are no zip or tar files, make sure cleanup is not a parameter
            else:
                assert 'cleanup' not in params

        # check that the download method can be called without errors
        if hasattr(dataset, 'REMOTES'):
            mock_downloader = mocker.patch.object(dataset, 'REMOTES')
            dataset.download()
            mocker.resetall()

            # check that links are online
            for key in dataset.REMOTES:
                # skip this test if it's in known issues
                if dataset_name in KNOWN_ISSUES and key in KNOWN_ISSUES[dataset_name]:
                    continue

                url = dataset.REMOTES[key].url
                try:
                    request = requests.head(url)
                    assert request.ok
                except requests.exceptions.ConnectionError:
                    print('Link {} for {} is unreachable'.format(url, dataset_name))
                    assert False
        else:
            dataset.download()


# This is magically skipped by the the remote fixture `skip_local` in conftest.py
# when tests are run with the --local flag
def test_validate(skip_local):
    for dataset in DATASETS:
        data_home = os.path.join('tests/resources/mir_datasets', dataset.DATASET_DIR)
        dataset.validate(data_home=data_home)
        dataset.validate(data_home=data_home, silence=True)
        dataset.validate(data_home=None, silence=True)


def test_load_and_trackids():
    for dataset in DATASETS:
        track_ids = dataset.track_ids()
        assert type(track_ids) is list
        trackid_len = len(track_ids)

        data_home = os.path.join('tests/resources/mir_datasets', dataset.DATASET_DIR)
        dataset_data = dataset.load(data_home=data_home)
        assert type(dataset_data) is dict
        assert len(dataset_data.keys()) == trackid_len

        dataset_data_default = dataset.load()
        assert type(dataset_data_default) is dict
        assert len(dataset_data_default.keys()) == trackid_len


def test_track():
    data_home_dir = 'tests/resources/mir_datasets'

    for dataset in DATASETS:
        dataset_name = dataset.__name__.split('.')[1]
        print(dataset_name)

        if dataset_name in CUSTOM_TEST_TRACKS:
            trackid = CUSTOM_TEST_TRACKS[dataset_name]
        else:
            trackid = dataset.track_ids()[0]

        track_default = dataset.Track(trackid)
        assert track_default._data_home == os.path.join(
            DEFAULT_DATA_HOME, dataset.DATASET_DIR
        )

        # test data home specified
        data_home = os.path.join(data_home_dir, dataset.DATASET_DIR)
        track_test = dataset.Track(trackid, data_home=data_home)

        assert isinstance(track_test, track.Track)

        assert hasattr(track_test, 'to_jams')

        # Validate JSON schema
        jam = track_test.to_jams()
        assert jam.validate()

        # will fail if something goes wrong with __repr__
        print(track_test)

        with pytest.raises(ValueError):
            dataset.Track('~faketrackid~?!')

        track_custom = dataset.Track(trackid, data_home='casa/de/data')
        assert track_custom._data_home == 'casa/de/data'


# for load_* functions which require more than one argument
# module_name : {function_name: {parameter2: value, parameter3: value}}
EXCEPTIONS = {
    'dali': {'load_annotations_granularity': {'granularity': 'notes'}},
    'guitarset': {
        'load_pitch_contour': {'string_num': 1},
        'load_note_ann': {'string_num': 1},
    },
}


def test_load_methods():
    for dataset in DATASETS:
        dataset_name = dataset.__name__.split('.')[1]

        all_methods = dir(dataset)
        load_methods = [
            getattr(dataset, m) for m in all_methods if m.startswith('load_')
        ]
        for load_method in load_methods:
            method_name = load_method.__name__
            params = [
                p
                for p in signature(load_method).parameters.values()
                if p.default == inspect._empty
            ]  # get list of parameters that don't have defaults

            # add to the EXCEPTIONS dictionary above if your load_* function needs
            # more than one argument.
            if dataset_name in EXCEPTIONS and method_name in EXCEPTIONS[dataset_name]:
                extra_params = EXCEPTIONS[dataset_name][method_name]
                with pytest.raises(IOError):
                    load_method("a/fake/filepath", **extra_params)
            else:
                with pytest.raises(IOError):
                    load_method("a/fake/filepath")
