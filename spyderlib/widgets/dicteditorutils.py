# -*- coding: utf-8 -*-
#
# Copyright © 2011 Pierre Raybaut
# Licensed under the terms of the MIT License
# (see spyderlib/__init__.py for details)

"""
Utilities for the Dictionary Editor Widget and Dialog based on Qt
"""

from __future__ import print_function

import re

# Local imports
from spyderlib.py3compat import (to_text_string, is_text_string, is_binary_string, reprlib)
from spyderlib.utils import programs
from spyderlib import dependencies
from spyderlib.baseconfig import _


class FakeObject(object):
    """Fake class used in replacement of missing modules"""
    pass


#----Numpy arrays support
try:
    from numpy import array, matrix #@UnusedImport (object eval)
    from numpy.ma import MaskedArray
    from numpy import ndarray
except ImportError:
    ndarray = array = matrix = MaskedArray = FakeObject  # analysis:ignore


def get_numpy_dtype(obj):
    """Return NumPy data type associated to obj
    Return None if NumPy is not available
    or if obj is not a NumPy array or scalar"""
    if ndarray is not FakeObject:
        # NumPy is available
        import numpy as np
        if isinstance(obj, np.generic) or isinstance(obj, np.ndarray):
        # Numpy scalars all inherit from np.generic.
        # Numpy arrays all inherit from np.ndarray.
        # If we check that we are certain we have one of these
        # types then we are less likely to generate an exception below.
            try:
                return obj.dtype.type
            except (AttributeError, RuntimeError):
                #  AttributeError: some NumPy objects have no dtype attribute
                #  RuntimeError: happens with NetCDF objects (Issue 998)
                return


#----Pandas support
PANDAS_REQVER = '>=0.13.1'
dependencies.add('pandas',  _("View and edit DataFrames and Series in the "
                              "Variable Explorer"),
                 required_version=PANDAS_REQVER)
if programs.is_module_installed('pandas', PANDAS_REQVER):
    from pandas import DataFrame, TimeSeries
else:
    DataFrame = TimeSeries = FakeObject      # analysis:ignore


#----PIL Images support
try:
    from spyderlib import pil_patch
    Image = pil_patch.Image.Image
except ImportError:
    Image = FakeObject  # analysis:ignore


#----Misc.



#----Set limits for the amount of elements in the repr of collections
#    (lists, dicts, tuples and sets)
CollectionsRepr = reprlib.Repr()
CollectionsRepr.maxlist = 1000
CollectionsRepr.maxdict = 1000
CollectionsRepr.maxtuple = 1000
CollectionsRepr.maxset = 1000


#----date and datetime objects support
import datetime
try:
    from dateutil.parser import parse as dateparse
except ImportError:
    def dateparse(datestr):  # analysis:ignore
        """Just for 'year, month, day' strings"""
        return datetime.datetime( *list(map(int, datestr.split(','))) )
def datestr_to_datetime(value):
    rp = value.rfind('(')+1
    v = dateparse(value[rp:-1])
    print(value, "-->", v)
    return v



#----Sorting
def sort_against(lista, listb, reverse=False):
    """Arrange lista items in the same order as sorted(listb)"""
    try:
        return [item for _, item in sorted(zip(listb, lista), reverse=reverse)]
    except:
        return lista

def unsorted_unique(lista):
    """Removes duplicates from lista neglecting its initial ordering"""
    return list(set(lista))


    

#-------- get_basic_props stuff

def get_basic_props(self, key, value):
    """ 
    This is called by monitor.
    
    key: key name of variable 
    type_str: the type name to display when in non-compact mode
                and at the top of the tooltip in compact mode
    size_str: same as type_str but for the size_str
    value_str: full str to display in non-compact mode, may need to truncate.
    flag_colors: tuple of hex color codes to pass into a QColor(..)
                these are rendered as a flag in the delegate's paint event.
    editor_switch: string name indicating what kind of editor to launch
                see createEditor in delegate for details.                    
    plot_switch_tuple - list of plot types to show in context menu
                see ???? in tableview for details
    The additional data for the tooltip in compact mode is provided
    in get_meta_dict.
    """        
    props = {'key': key, 
             'type_str': value_to_type_str(value),
             'size_str':  value_to_size_str(value),                 
             'editor_switch': value_to_editor_switch(value),
             'plot_switch_tuple': value_to_plot_tuple(value), 
             'value_str': value_to_str(value), 
             'flag_colors': value_to_color_tuple(value)
             }
    return props
        
from inspect import getmro
from binascii import crc32

def value_to_type_str(item):
    """Return human-readable type string of an item"""
    if isinstance(item, (ndarray, MaskedArray)):
        return item.dtype.name
    elif isinstance(item, Image):
        return "Image"
    elif isinstance(item, DataFrame):
        return "DataFrame"
    elif isinstance(item, TimeSeries):
        return "TimeSeries"    
    else:
        found = re.findall(r"<(?:type|class) '(\S*)'>", str(type(item)))
        if found:
            return found[0].split('.', 1)[-1]
        else:
            return 'unknown'

def value_to_size_str(item):
    """Return size of an item of arbitrary type"""
    if isinstance(item, (list, tuple, dict, set)):
        s = len(item)
    elif isinstance(item, (ndarray, MaskedArray)):
        s = item.shape
    elif isinstance(item, Image):
        s = item.size
    if isinstance(item, (DataFrame, TimeSeries)):
        s = item.shape
    elif hasattr(item,'__len__'):
        s = len(item)
    else:
        s = 1
        
    if hasattr(s, '__len__'):
        return ' x '.join([str(ss) for ss in s])
    else:
        return str(s)
    

def value_to_str(value):   
    # <classname @ address>
    address = lambda obj: "<%s @ %s>" % (obj.__class__.__name__,
                              hex(id(obj)).upper().replace('X', 'x'))
    
    if isinstance(value, Image):
        return '%s  Mode: %s' % (address(value), value.mode)
    if isinstance(value, DataFrame):
        cols = value.columns
        cols = [to_text_string(c) for c in cols]
        return 'Column names: ' + ', '.join(list(cols))
    if is_binary_string(value):
        try:
            return to_text_string(value, 'utf8')
        except:
            return value
    if not is_text_string(value):
        if isinstance(value, (list, tuple, dict, set)):
            return CollectionsRepr.repr(value)
        else:
            return repr(value)

    
def value_to_color_tuple(value):
    """ Hashes the names of base classes into a list of hex colors    
    """
    try:
        mro = getmro(value)
    except AttributeError:
        try:
            mro = getmro(type(value))
        except Exception:
            mro = []
    str_to_color = lambda s: '#' + hex(crc32(s) & 0xffffff)[2:]
    return tuple(str_to_color(getattr(t, '__name__', 'none')) for t in mro)

def value_to_plot_tuple(value):
    """ Returns a list of strings indicating what plots to offer for given value.
    """
    return () # TODO: this
    
    
def value_to_editor_switch(value):
    """ Returns a string saying which kind of editor to use or None
    """
    return None # TODO: this
    
#-----Make meta dict stuff
    
import os.path as osp
from spyderlib.config import CONF

# On startup, find the required implementation
make_meta_dict_inner_func = None

mod_custom_path = CONF.get('variable_explorer', 'make_meta_dict', False)
makemetadict_def = CONF.get('variable_explorer', 'makemetadict/default', False)

if not makemetadict_def and osp.exists(str(mod_custom_path)):
    # Loading a module form file path seems to be messy:
    # http://stackoverflow.com/a/67692/2399799
    mod_custom_name, _ = osp.splitext(mod_custom_path)
    mod = None
    try:
        import imp
        mod = imp.load_source(mod_custom_name, mod_custom_path)
    except Exception:
        try:
            import importlib.machinery
            mod = importlib.machinery\
                            .SourceFileLoader(mod_custom_name, mod_custom_path)\
                            .load_module(mod_custom_name)
        except Exception:
            pass  # mod is still None, use default...
    if mod is not None:
        make_meta_dict_inner_func = getattr(mod, 'make_meta_dict', None)
        
if make_meta_dict_inner_func is None:
    from spyderlib.make_meta_dict_default import make_meta_dict
    make_meta_dict_inner_func = make_meta_dict


def make_meta_dict(value):
    """
    This wraps the user's code, giving a stacktrace on errors, but still
    returning a valid output.  The idea is that the make_meta_dict_func
    is located in a separate file that can be modified by the user 
    (like the startup.py scripts).
    """
    try:
        return make_meta_dict_inner_func(value)
    except Exception:
        import traceback
        print(traceback.format_exc())
        return {}


