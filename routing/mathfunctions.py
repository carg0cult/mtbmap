# -*- coding: utf-8 -*-

# Global imports
from math import radians, cos, sin, asin, sqrt

def haversine(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    # haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    km = 6378.137 * c
    return km

def total_seconds(time_diff):
    """
    Calculate datetime.timedelta in total seconds. Needed for Python versions < 2.7.
    """
    return (time_diff.microseconds + (time_diff.seconds + time_diff.days * 24 * 3600) * 1e6) / 1e6

def hypotenuse(x1, y1, x2, y2):
    """
    Calculate length of hypotenuse for given coordinates.
    """
    return sqrt((x2-x1)**2 + (y2-y1)**2)