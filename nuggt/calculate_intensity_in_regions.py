import argparse
import glob
import json
import multiprocessing
import numpy as np
import os
import sys
import tifffile
import tqdm

from phathom.utils import SharedMemory

from .brain_regions import BrainRegions
from nuggt.utils.warp import Warper


def parse_args(args=sys.argv[1:]):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",
                        help="The glob expression for the stack to be "
                        "measured",
                        required=True)
    parser.add_argument("--alignment",
                        help="The points file from nuggt-align",
                        required=True)
    parser.add_argument("--reference-segmentation",
                        help="The reference segmentation that we map to.",
                        required=True)
    parser.add_argument("--brain-regions-csv",
                        help="The .csv file that provides the correspondences "
                        "between segmentation IDs and their brain region names",
                        required=True)
    parser.add_argument("--output",
                        help="The name of the .csv file to be written",
                        required=True)
    parser.add_argument("--level",
                        help="The granularity level (1 to 7 with 7 as the "
                             "finest level. Default is the finest.",
                        type=int,
                        default=7)
    parser.add_argument("--n-cores",
                        type=int,
                        default=os.cpu_count(),
                        help="The number of processes to use")
    return parser.parse_args(args)


def do_plane(filename:str, z:int, segmentation: SharedMemory, warper:Warper):
    """Process one plane

    :param filename: the name of the tiff file holding the plane
    :param z: The z-coordinate of the tiff file
    :param segmentation: the shared-memory holder of the segmentation.
    :return: a two tuple of the counts per region and total intensities per
    region.
    """
    plane = tifffile.imread(filename)
    zz, yy, xx = [_.flatten() for _ in
                  np.mgrid[z:z+1, 0:plane.shape[0], 0:plane.shape[1]]]
    awarper = warper.approximate(np.array([z-1, z, z+1]),
                                 np.linspace(0, plane.shape[0] - 1, 100),
                                 np.linspace(0, plane.shape[1] - 1, 100))
    zseg, yseg, xseg = awarper(np.column_stack((zz, yy, xx))).transpose()
    zseg = np.round(zseg).astype(np.int32)
    yseg = np.round(yseg).astype(np.int32)
    xseg = np.round(xseg).astype(np.int32)
    mask = (xseg >= 0) & (xseg < segmentation.shape[2]) &\
           (yseg >= 0) & (yseg < segmentation.shape[1]) &\
           (zseg >= 0) & (zseg < segmentation.shape[0])
    with segmentation.txn() as m:
        send = np.max(m) + 1
        seg = m[zseg[mask], yseg[mask], xseg[mask]]
        counts = np.bincount(seg, minlength=send)
        sums = np.bincount(seg, plane.flatten()[mask].astype(np.int64),
                           minlength=send)
    return counts, sums


def main(args=sys.argv[1:]):
    args = parse_args(args)
    alignment = json.load(open(args.alignment))
    warper = Warper(alignment["moving"], alignment["reference"])
    segmentation = tifffile.imread(args.reference_segmentation)\
        .astype(np.uint16)
    sm_segmentation = SharedMemory(segmentation.shape,
                                   segmentation.dtype)
    with sm_segmentation.txn() as m:
        m[:] = segmentation
    files = glob.glob(args.input)
    if len(files) == 0:
        raise IOError("Failed to find any files matching %s" % args.input)
    total_counts = np.zeros(np.max(segmentation) + 1, np.int64)
    total_sums = np.zeros(np.max(segmentation) + 1, np.int64)
    if args.n_cores == 1:
        for z, filename in tqdm.tqdm(enumerate(files), total=len(files)):
            c, s = do_plane(filename, z, sm_segmentation, warper)
            total_counts += c
            total_sums += s
    else:
        with multiprocessing.Pool(args.n_cores) as pool:
            futures = []
            for z, filename in enumerate(files):
                future = pool.apply_async(
                    do_plane,
                    (filename, z, sm_segmentation, warper))
                futures.append(future)

            for future in tqdm.tqdm(futures):
                c, s = future.get()
                total_counts += c
                total_sums += s

    with open(args.brain_regions_csv) as fd:
        br = BrainRegions.parse(fd)

    seg_ids = np.where(total_counts > 0)[0]
    counts_per_id = total_counts[seg_ids]
    total_intensities_per_id = total_sums[seg_ids]
    mean_intensity_per_id = \
        total_intensities_per_id.astype(float) / counts_per_id
    if args.level == 7:
        with open(args.output, "w") as fd:
            fd.write(
                '"id","region","area","total_intensity","mean_intensity"\n')
            for seg_id, count, total_intensity, mean_intensity in zip(
                    seg_ids, counts_per_id, total_intensities_per_id,
                    mean_intensity_per_id):
                if seg_id == 0:
                    region = "not in any region"
                else:
                    region = br.name_per_id.get(seg_id, "id%d" % seg_id)
                fd.write('%d,"%s",%d, %d, %.2f\n' %
                         (seg_id, region, count, total_intensity,
                          mean_intensity))
    else:
        d = {}
        for seg_id, count, intensity in zip(
                seg_ids, counts_per_id, total_intensities_per_id):
            level = br.get_level_name(seg_id, args.level)
            if level in d:
                d[level][0] += count
                d[level][1] += intensity
            else:
                d[level] = (count, intensity)
        with open(args.output, "w") as fd:
            fd.write('"region","area", "total_intensity","mean_intensity"\n')
            for level in sorted(d):
                fd.write('"%s",%d,%d,%.2f\n' %
                         (level, d[level][0], d[level][1],
                          d[level][1] / d[level][0]))


if __name__=="__main__":
    main()
