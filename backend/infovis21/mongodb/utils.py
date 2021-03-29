import itertools
import math
import time
from pprint import pprint

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.neighbors import KDTree

from infovis21.mongodb import MongoAccess as ma


def normalize(dim, value, _min=0.0, _max=1.0):
    """ Normalize orignal data values """
    return np.interp(
        value, (ma.dim_minmax[dim]["min"], ma.dim_minmax[dim]["max"]), (_min, _max),
    )


def create_vector(node):
    """ extract feature vector from a track document """
    return np.array([node[dim] for dim in ma.dimensions])


def _precomputed_collection(dimx, dimy, typ, zoom, *args):
    return ma.db["_".join([dimx, dimy, typ, str(zoom)] + list(args))]


def precomputed_nodes_collection(dimx, dimy, typ, zoom):
    return _precomputed_collection(dimx, dimy, typ, zoom, "nodes")


def precomputed_links_collection(dimx, dimy, typ, zoom):
    return _precomputed_collection(dimx, dimy, typ, zoom, "links")


def precomputed_discarded_collection(dimx, dimy, typ, zoom):
    return _precomputed_collection(dimx, dimy, typ, zoom, "discarded")


MAX_RADIUS = 0.1
N_ZOOM_LEVELS = 5
ZOOM_LEVELS = [MAX_RADIUS / (2 ** i) for i in range(N_ZOOM_LEVELS - 1)] + [0.0]


def precompute_nodes(dimx, dimy, typ, zoom, offset=0, limit=None, plot=False):
    print("-" * 50)
    print("precomputing", dimx, dimy, typ, zoom, ZOOM_LEVELS[zoom])
    nodes_out = precomputed_nodes_collection(dimx, dimy, typ, zoom)
    links_out = precomputed_links_collection(dimx, dimy, typ, zoom)
    discarded_out = precomputed_discarded_collection(dimx, dimy, typ, zoom)

    mongo_values = ma.map_zoom_to_mongo(typ)
    album_label = mongo_values["album_label"]
    id_key = mongo_values["id_val"]

    radius = ZOOM_LEVELS[zoom]
    pipeline = [
        {"$match": {}},
        {"$sort": {id_key: ma.DESC}},
        {"$skip": int(offset)},
    ]
    if limit is not None:
        pipeline.append({"$limit": int(limit)})

    # load all nodes from the database
    nodes_data = dict()
    for idx, elem in enumerate(ma.collections[typ].aggregate(pipeline)):
        x, y = normalize(dimx, elem.get(dimx)), normalize(dimy, elem.get(dimy))
        nodes_data[elem.get(id_key)] = (np.array([x, y]), elem.get(id_key), elem)
        # pprint(elem)
    print("got %d nodes" % len(nodes_data))

    # filter nodes based on distance
    points, _, _ = zip(*nodes_data.values())
    filtered, discarded, duration = min_distance_based_filtering(points, radius=radius)
    filtered_nodes = [list(nodes_data.values())[idx] for idx in filtered]
    preprocessed_nodes = [
        {**node, **{"x": pos[0], "y": pos[1]}} for pos, _, node in filtered_nodes
    ]
    # pprint(nodes[:10])

    filtered_points, filtered_node_ids, _ = zip(*filtered_nodes)
    print(
        "reduced from %d to %d in %f sec"
        % (len(nodes_data), len(filtered_nodes), duration)
    )

    # plot filtered nodes
    if plot:
        dims = ["x", "y"]
        sns.scatterplot(data=pd.DataFrame(points, columns=dims), x="x", y="y")
        plt.show()
        sns.scatterplot(data=pd.DataFrame(filtered_nodes, columns=dims), x="x", y="y")
        plt.show()

    # compute all visible links with their coordinates so that they can be queried
    # more efficiently
    pipeline = [
        {"$unwind": album_label},
        {"$group": {"_id": album_label, "members": {"$addToSet": "$" + id_key},}},
        {
            "$project": {
                "id": "$_id",
                "members": "$members",
                "color": "black",  # needs to be set programmatically
            }
        },
    ]

    preprocessed_links = []
    filtered_node_ids = set(filtered_node_ids)
    for idx, music_label in enumerate(ma.collections[typ].aggregate(pipeline)):
        members = set(music_label["members"])
        link_nodes = members.intersection(filtered_node_ids)
        if len(link_nodes) == 2:
            src_id, dest_id = link_nodes
            (src_pos, src, _), (dest_pos, dest, _) = (
                nodes_data.get(src_id),
                nodes_data.get(dest_id),
            )
            preprocessed_links.append(
                {
                    "src": src_id,
                    "dest": dest_id,
                    "color": music_label.get("color"),
                    "name": music_label.get("id"),
                    "x1": src_pos[0],
                    "y1": src_pos[1],
                    "x2": dest_pos[0],
                    "y2": dest_pos[1],
                    # "x_min": min(src_pos[0], dest_pos[0]),
                    # "x_max": max(src_pos[0], dest_pos[0]),
                    # "y_min": min(src_pos[1], dest_pos[1]),
                    # "y_max": max(src_pos[1], dest_pos[1]),
                }
            )

    print("computed %d links" % len(preprocessed_links))

    nodes_out.drop()
    if len(preprocessed_nodes) > 0:
        nodes_out.insert_many(preprocessed_nodes)
    links_out.drop()
    if len(preprocessed_links) > 0:
        links_out.insert_many(preprocessed_links)
    discarded_out.drop()


def min_distance_based_filtering(points, radius=0.1, verbosity=100_000):
    points_idx = set(range(len(points)))
    taken, ans, visited = set(), list(), set()

    radius = abs(radius)
    if radius == 0:
        return points_idx, None, 0

    start = time.time()
    tree = KDTree(points)

    lo, hi = (0, 0), (1.0, 1.0)
    cell_size = (2 * radius, 2 * radius)
    # print("cell size is", cell_size)
    grid_size = (
        math.ceil(abs(hi[0] - lo[0]) / cell_size[0]),
        math.ceil(abs(hi[1] - lo[1]) / cell_size[1]),
    )
    # print("grid size is", grid_size)

    grid = [[set()] * grid_size[1] for _ in range(grid_size[0])]

    last_visited = 0
    while len(visited) < len(points):
        idx = points_idx.pop()
        visited.add(idx)

        if len(visited) // verbosity > last_visited:
            print(len(visited), "of", len(points))
            last_visited = len(visited) // verbosity

        p = points[idx]
        px, py = (p // cell_size).astype(int)
        # print(px, py)
        neighbours = set(tree.query_radius([p], r=radius)[0])
        if all((n_idx not in taken) for n_idx in neighbours):
            taken.add(idx)
            ans.append(idx)
            visited = visited.union(neighbours)
            grid[px][py] = grid[px][py].union(neighbours)
            points_idx = points_idx.difference(neighbours)
        else:
            points_idx.add(idx)

    discarded = np.zeros(shape=grid_size)
    for row, col in itertools.product(*[range(x) for x in grid_size]):
        discarded[row][col] = len(grid[row][col])

    end = time.time()
    return ans, discarded, end - start


def create_album_collection():
    pipeline = [
        {"$unwind": "$tracks"},
        {
            "$lookup": {
                "from": "tracks",
                "localField": "tracks.id",
                "foreignField": "id",
                "as": "track_docs",
            }
        },
        {"$unwind": "$track_docs"},
        {
            "$group": {
                "_id": "$id",
                "acousticness": {"$avg": "$track_docs.acousticness"},
                "danceability": {"$avg": "$track_docs.danceability"},
                "duration_ms": {"$avg": "$track_docs.duration_ms"},
                "energy": {"$avg": "$track_docs.energy"},
                "explicit": {"$avg": "$track_docs.explicit"},
                "instrumentalness": {"$avg": "$track_docs.instrumentalness"},
                "key": {"$avg": "$track_docs.key"},
                "liveness": {"$avg": "$track_docs.liveness"},
                "loudness": {"$avg": "$track_docs.loudness"},
                "mode": {"$avg": "$track_docs.mode"},
                "popularity": {"$avg": "$track_docs.popularity"},
                "speechiness": {"$avg": "$track_docs.speechiness"},
                "tempo": {"$avg": "$track_docs.tempo"},
                "valence": {"$avg": "$track_docs.valence"},
                "year": {"$avg": "$track_docs.year"},
                "tracks": {"$addToSet": "$tracks"},
                "genres": {"$first": "$genres"},
                "type": {"$first": "$type"},
                "oid": {"$first": "$_id"},
                "album_type": {"$first": "$album_type"},
                "artists": {"$first": "$artists"},
                "label": {"$first": "$label"},
                "name": {"$first": "$name"},
                "popularity": {"$first": "$popularity"},
                "release_date": {"$first": "$release_date"},
                "release_date_precision": {"$first": "$release_date_precision"},
                "total_tracks": {"$first": "$total_tracks"},
            }
        },
        {"$set": {"_id": "$oid", "id": "$_id"}},
        {"$unset": "oid"},
        # {"$out": "album_audio_analysis"},
    ]
    return list(ma.coll_albums.aggregate(pipeline, allowDiskUse=True))


def add_labels_to_genres():
    pipeline = [
        {"$unwind": "$genres"},
        {"$unwind": "$labels"},
        {"$group": {"_id": "$genres", "labels": {"$addToSet": "$labels"},}},
        {
            "$lookup": {
                "from": "genres",
                "localField": "_id",
                "foreignField": "genres",
                "as": "genre_lookup",
            }
        },
        {"$unwind": "$genre_lookup"},
        {"$set": {"genre_lookup.labels": "$labels"}},
        {"$replaceRoot": {"newRoot": "$genre_lookup"}},
        # {"$out": "genres_with_labels"},
    ]
    return list(ma.coll_artists.aggregate(pipeline))


def compute_min_max():
    pipeline = [
        {
            "$group": {
                "_id": None,
                "min_acousticness": {"$min": "$acousticness"},
                "min_danceability": {"$min": "$danceability"},
                "min_duration_ms": {"$min": "$duration_ms"},
                "min_energy": {"$min": "$energy"},
                "min_explicit": {"$min": "$explicit"},
                "min_instrumentalness": {"$min": "$instrumentalness"},
                "min_key": {"$min": "$key"},
                "min_liveness": {"$min": "$liveness"},
                "min_loudness": {"$min": "$loudness"},
                "min_mode": {"$min": "$mode"},
                "min_popularity": {"$min": "$popularity"},
                "min_speechiness": {"$min": "$speechiness"},
                "min_tempo": {"$min": "$tempo"},
                "min_valence": {"$min": "$valence"},
                "min_year": {"$min": "$year"},
                "max_acousticness": {"$max": "$acousticness"},
                "max_danceability": {"$max": "$danceability"},
                "max_duration_ms": {"$max": "$duration_ms"},
                "max_energy": {"$max": "$energy"},
                "max_explicit": {"$max": "$explicit"},
                "max_instrumentalness": {"$max": "$instrumentalness"},
                "max_key": {"$max": "$key"},
                "max_liveness": {"$max": "$liveness"},
                "max_loudness": {"$max": "$loudness"},
                "max_mode": {"$max": "$mode"},
                "max_popularity": {"$max": "$popularity"},
                "max_speechiness": {"$max": "$speechiness"},
                "max_tempo": {"$max": "$tempo"},
                "max_valence": {"$max": "$valence"},
                "max_year": {"$max": "$year"},
            }
        },
        {
            "$project": {
                "acousticness": {
                    "min": "$min_acousticness",
                    "max": "$max_acousticness",
                },
                "danceability": {
                    "min": "$min_acousticness",
                    "max": "$max_danceability",
                },
                "duration_ms": {"min": "$min_duration_ms", "max": "$max_duration_ms",},
                "energy": {"min": "$min_energy", "max": "$max_energy",},
                "explicit": {"min": "$min_explicit", "max": "$max_explicit",},
                "instrumentalness": {
                    "min": "$min_instrumentalness",
                    "max": "$max_instrumentalness",
                },
                "key": {"min": "$min_key", "max": "$max_key",},
                "liveness": {"min": "$min_liveness", "max": "$max_liveness",},
                "loudness": {"min": "$min_loudness", "max": "$max_loudness",},
                "mode": {"min": "$min_mode", "max": "$max_mode",},
                "popularity": {"min": "$min_popularity", "max": "$max_popularity",},
                "speechiness": {"min": "$min_speechiness", "max": "$max_speechiness",},
                "tempo": {"min": "$min_tempo", "max": "$max_tempo",},
                "valence": {"min": "$min_valence", "max": "$max_valence",},
                "year": {"min": "$min_year", "max": "$max_year",},
                "_id": 0,
            }
        },
    ]
    return list(ma.coll_tracks.aggregate(pipeline))[0]
