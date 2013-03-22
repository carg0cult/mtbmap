#!/usr/bin/python
# -*- coding: utf-8 -*-
from map.models import Way, WeightClass
from django.db import connection
from django.contrib.gis.geos import *
from datetime import datetime

WEIGHTS = [1, 2, 3, 4, 5]
MAX_WEIGHT = max(WEIGHTS)
MIN_WEIGHT = min(WEIGHTS)

def line_string_to_points(line_string):
    '''
    Parse line geometry, represented as a string.
    return array of GEOS Points
    '''
    latlngs = [coord.strip().replace('LatLng(', '').replace(')','') for coord in line_string.replace('[', '').replace(']', '').split(',')]
    point_strings = [latlngs[i+1] + ' ' + latlngs[i] for i in range(0, len(latlngs), 2)]
    return [GEOSGeometry('SRID=4326;POINT(%s)' % point) for point in point_strings]


class MultiRoute:
    def __init__(self, points, params):
        self.params = RouteParams(self._recreate_params(params))
        self.points = points
        self.length = 0
        self.cost = 0
        self.last_route = None
        self.status = 'init'
        self.geojson_features = []

    def _recreate_params(self, flat_params):
        '''
        Given JSON like object, create better python dictionary.
        '''
        new = {}
        for p in flat_params:
            classname, feature = p['name'].split('__')
            if not classname in new:
                new[classname] = {}
            new[classname][feature] = p['value']
        return new

    def geojson(self):
        '''
        Create GeoJSON like object of type FeatureCollection.
        '''
        return {
            'type': 'FeatureCollection',
            'properties': {
                'status': self.status,
                'length': self.length
            },
            'features': self.geojson_features
        }

    def search_index(self):
        '''
        Compute ratio between cost and real length of the road
        '''
        if self.length>0:
            return self.cost/self.length
        else:
            return -1

    def find_multiroute(self):
        '''
        Find route between all points, according to given params.
        '''
        start = datetime.now()
        for i in range(len(self.points)-1):
            start_point = self.points[i]
            end_point = self.points[i+1]
            route = Route(start_point, end_point, self.params, self.last_route)
            route.find_best_route()
            if route.status == 'notfound':
                self.status = route.status
            self.length += route.length
            self.cost += route.cost
            self.geojson_features += route.geojson()
            self.last_route = route
        if self.status=='init':
            self.status = 'success'
        end = datetime.now()
        print 'Find MultiRoute duration:', (end - start).total_seconds()
        return self.status

class Route:
    def __init__(self, start_point, end_point, params, previous_route=None):
        self.status = 'init'
        self.start_point = start_point
        self.end_point = end_point
#        self.bbox = MultiPoint(self.start_point, self.end_point).envelope
        self.params = params
        self.previous_route = previous_route
        self.length = 0
        self.cost = 0
        self.ways = None
#        nearest_start = datetime.now()
        if self.previous_route:
            self.start_way = self.previous_route.end_way
            self.start_to_source = self.previous_route.end_to_source
            self.start_to_target = self.previous_route.end_to_target
        else:
            self.start_way = self.nearest_way(start_point)
            self.start_to_source, self.start_to_target = self.start_way.lines_to_endpoints(start_point)
#        nearest_middle = datetime.now()
#        print 'Start way:', (nearest_middle-nearest_start).total_seconds()
        self.end_way = self.nearest_way(end_point)
        self.end_to_source, self.end_to_target = self.end_way.lines_to_endpoints(end_point)
#        nearest_end = datetime.now()
#        print 'End way:  ', (nearest_end-nearest_middle).total_seconds()

    def find_best_route(self):
        '''
        Find route with the smallest cost.
        '''
        if self.start_way.id==self.end_way.id:
            # both endpoints on the same way
            way_part = self.start_way.point_to_point(self.start_point, self.end_point)
            self.status = 'success'
            self.ways = [way_part]
            self.length = way_part.length
            self.cost = self.length * way_part.weight(self.params.raw_params)
            return self.status
        else:
            temp1, temp2, start_id, to_start_way = self.start_way.split(self.start_point)
            temp3, temp4, end_id, to_end_way = self.end_way.split(self.end_point)
            limit_way = self.insert_limit_way(start_id, end_id, self.start_point, self.end_point)
            # use dijkstra or astar search
            edge_ids = self.astar(start_id, end_id)
#            edge_ids = self.dijkstra(start_id, end_id)
            if limit_way.id in edge_ids:
                self.status = 'notfound'
            else:
                self.status = 'success'
            ways = [to_start_way]
            for id in edge_ids[:-1]:
                ways.append(Way.objects.get(pk=id))
            ways.append(to_end_way)
            self.ways = ways
#            self.ways = Way.objects.filter(id__in=edge_ids)
            self.length = sum([way.length for way in self.ways])
            temp1.delete()
            temp2.delete()
            temp3.delete()
            temp4.delete()
            limit_way.delete()
            return self.status

    def geojson(self):
        if self.status=='init':
            self.find_best_route()
        return [way.feature(self.params.raw_params, self.status) for way in self.ways]

    def search_index(self):
        '''
        Compute ratio between cost and real length of the road
        '''
        if self.length>0:
            return self.cost/self.length
        else:
            return -1

    def astar(self, source, target):
        '''
        Search route from source to target points with A Star algorithm
        implemented by pgRouting.
        return array of edge IDs of Way objects
        '''
#        start = datetime.now()
        cursor = connection.cursor()
        print self.params.sql_astar
        cursor.execute("SELECT edge_id, cost FROM shortest_path_astar(%s, %s, %s, false, false)", [self.params.sql_astar, source, target])
        rows = cursor.fetchall()
        edge_ids = [elem[0] for elem in rows]
        self.cost = sum([elem[1] for elem in rows])
#        end = datetime.now()
#        print 'astar finished', (end - start).total_seconds()
        return edge_ids

    def dijkstra(self, source, target):
        '''
        Search route from source to target points with Dijkstra algorithm
        implemented by pgRouting.
        return array of edge IDs of Way objects
        '''
        cursor = connection.cursor()
        cursor.execute("SELECT edge_id FROM shortest_path(%s, %s, %s, false, false)", [self.params.sql_dijkstra, source, target])
        rows = cursor.fetchall()
        edge_ids = [elem[0] for elem in rows]
        self.cost = sum([elem[1] for elem in rows])
        return edge_ids

    def nearest_way(self, point):
        '''
        Find nearest way from given point(latlon) and apply weight of the way.
        return Way
        '''
        # initial distance radius in kilometers
        radius = 0.001
        bbox = point.buffer(radius).envelope
        found = False
        while not found:
            bbox = point.buffer(radius).envelope
            ways = Way.objects.filter(the_geom__bboverlaps=bbox).extra(where=[self.params.where]).distance(point).order_by('distance')
            if ways.count():
                best_weight = ways[0].weight(self.params.raw_params) * ways[0].distance.km
                nearest_way = ways[0]
                for way in ways:
                    distance = way.distance.km
                    if distance>best_weight:
                        found=True
                        break
                    else:
                        weighted_distance = way.weight(self.params.raw_params) * way.distance.km
                        if weighted_distance<best_weight:
                            best_weight = weighted_distance
                            nearest_way = way
            radius *= 2
        return nearest_way

    def insert_limit_way(self, start_id, end_id, start_point, end_point):
        '''
        Insert into DB Way between start and end points. Can be used as threshold for route searching.
        return Way
        '''
        limit_way = Way( name='TEMP_LIMIT_WAY',
                         x1=start_point.x,
                         x2=end_point.x,
                         y1=start_point.y,
                         y2=end_point.y,
                         source=start_id,
                         target=end_id,
                         highway='temp'
                    )
        line = LineString((limit_way.x1, limit_way.y1), (limit_way.x2, limit_way.y2))
        line.set_srid(4326)
        limit_way.the_geom = line
        limit_way.save()        
        # workaround to compute correct length
        limit_way.length = 3 * MAX_WEIGHT * Way.objects.length().get(pk=limit_way.id).length.km
        limit_way.save()
        return limit_way

class RouteParams:
    def __init__(self, params):
        self.raw_params = params
        self.where = '(id IS NOT NULL)'
        self.cost = 'length'
        self._cost_and_where()
        self.sql_astar = self.weighted_ways_astar()
        self.sql_dijkstra = self.weighted_ways_dijkstra()

    def weighted_ways_astar(self):
        '''
        Create sql query for pgRouting A Star.
        return sql query string
        '''
        where = 'WHERE ' + self.where + " OR highway='temp'"
        return 'SELECT id, source::int4, target::int4, %s AS cost, x1, x2, y1, y2 FROM map_way %s' % (self.cost, where)

    def weighted_ways_dijkstra(self):
        '''
        Create sql query for pgRouting Dijkstra.
        return sql query string
        '''
        where = "WHERE " + self.where + " OR highway='temp'"
        return 'SELECT id, source::int4, target::int4, %s AS cost FROM map_way %s' % (self.cost, where)

    def _cost_and_where(self):
        '''
        Create cost column definition and where clause.
        '''
        cases = []
        whereparts = []
        whereparts.append(self._access())
        for wc in WeightClass.objects.all():
            cases += wc.get_when_clauses(self.raw_params[wc.classname])
            part = wc.get_where_clauses(self.raw_params[wc.classname])
            if part:
                whereparts.append(part)
        if cases:
            self.cost = 'CASE %s ELSE "length" END' % (' '.join(cases))
        if whereparts:
            self.where = "(" + " AND ".join(whereparts) + ")"

    def _access(self, role=None):
        '''
        Create access clause according to given role (car, bike, pedestrian,...)
        '''
        # exclude ways with access='no'
        return '''(access IS NULL OR access!='no')'''