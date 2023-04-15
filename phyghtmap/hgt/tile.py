import logging
from functools import cache
from typing import Any, Dict, Iterable, List, NamedTuple, Tuple

import numpy
import numpy.typing

from phyghtmap.contour import ContoursGenerator, build_contours
from phyghtmap.hgt import makeBBoxString, transformLonLats

meters2Feet = 1.0 / 0.3048

logger = logging.getLogger(__name__)


TileContours = NamedTuple(
    "TileContours",
    [
        # Total number of unique nodes
        ("nb_nodes", int),
        # Total number of ways
        ("nb_ways", int),
        # Contour lines per elevation
        ("contours", Dict[int, List[numpy.ndarray]]),
    ],
)


class hgtTile:
    """is a handle for hgt data tiles as generated by hgtFile.makeTiles()."""

    def __init__(self, tile_data: Dict[str, Any]):
        """initializes tile-specific variables. The minimum elevation is stored in
        self.minEle, the maximum elevation in self.maxEle.
        """
        self.minLon, self.minLat, self.maxLon, self.maxLat = tile_data["bbox"]
        self.zData = tile_data["data"]
        # initialize lists for longitude and latitude data
        self.numOfRows = self.zData.shape[0]
        self.numOfCols = self.zData.shape[1]
        self.lonIncrement, self.latIncrement = tile_data["increments"]
        self.polygons = tile_data["polygon"]
        self.mask = tile_data["mask"]
        self.transform = tile_data["transform"]
        self.xData = numpy.arange(self.numOfCols) * self.lonIncrement + self.minLon
        self.yData = numpy.arange(self.numOfRows) * self.latIncrement * -1 + self.maxLat
        self.minEle, self.maxEle = self.getElevRange()
        self.elevations = None
        self.contourData = None

    def get_stats(self) -> str:
        """Get some statistics about the tile."""
        minLon, minLat, maxLon, maxLat = transformLonLats(
            self.minLon, self.minLat, self.maxLon, self.maxLat, self.transform
        )
        result = (
            f"tile with {self.numOfRows:d} x {self.numOfCols:d} points, "
            f"bbox: ({minLon:.2f}, {minLat:.2f}, {maxLon:.2f}, {maxLat:.2f})"
            f"; minimum elevation: {self.minEle:.2f}; maximum elevation: {self.maxEle:.2f}"
        )
        return result

    def printStats(self) -> None:
        """prints some statistics about the tile."""
        print(f"\n{self.get_stats()}")

    def getElevRange(self) -> Tuple[int, int]:
        """returns minEle, maxEle of the current tile.

        We don't have to care about -0x8000 values here since these are masked
        so that self.zData's min and max methods will yield proper values.
        """
        minEle = int(self.zData.min())
        maxEle = int(self.zData.max())
        return minEle, maxEle

    def bbox(self, doTransform=True) -> Tuple[float, float, float, float]:
        """returns the bounding box of the current tile."""
        if doTransform:
            return transformLonLats(
                self.minLon, self.minLat, self.maxLon, self.maxLat, self.transform
            )
        else:
            return self.minLon, self.minLat, self.maxLon, self.maxLat

    def contourLines(
        self,
        stepCont=20,
        maxNodesPerWay=0,
        noZero=False,
        minCont=None,
        maxCont=None,
        rdpEpsilon=None,
    ) -> Tuple[Iterable[int], ContoursGenerator]:
        """generates contour lines using matplotlib.

        <stepCont> is height difference of contiguous contour lines in meters
        <maxNodesPerWay>:  the maximum number of nodes contained in each way
        <noZero>:  if True, the 0 m contour line is discarded
        <minCont>:  lower limit of the range to generate contour lines for
        <maxCont>:  upper limit of the range to generate contour lines for
        <rdpEpsilon>: epsilon to use in RDP contour line simplification

        A list of elevations and a ContourObject is returned.
        """

        def getContLimit(ele: int, step: int) -> int:
            """returns a proper value for the lower or upper limit to generate contour
            lines for.
            """
            if ele % step == 0:
                return ele
            corrEle: int = ele + step - ele % step
            return corrEle

        min_cont: int = minCont or getContLimit(self.minEle, stepCont)
        max_cont: int = maxCont or getContLimit(self.maxEle, stepCont)
        levels: Iterable[int]
        if noZero:
            levels = [
                level
                for level in range(int(min_cont), int(max_cont), stepCont)
                if level != 0
            ]
        else:
            levels = range(int(min_cont), int(max_cont), stepCont)
        x, y = numpy.meshgrid(self.xData, self.yData)
        # z data is a masked array filled with nan.
        z: numpy.typing.ArrayLike = numpy.ma.array(
            self.zData, mask=self.mask, fill_value=float("NaN"), keep_mask=True
        )

        contours: ContoursGenerator = build_contours(
            x, y, z, maxNodesPerWay, self.transform, self.polygons, rdpEpsilon
        )
        return levels, contours

    def plotData(self, plotPrefix="heightPlot") -> None:
        """generates plot data in the file specified by <plotFilename>."""
        filename = (
            makeBBoxString(self.bbox(doTransform=True)).format(plotPrefix + "_")
            + ".xyz"
        )
        try:
            plotFile = open(filename, "w")
        except Exception:
            raise IOError("could not open plot file {0:s} for writing".format(filename))
        for latIndex, row in enumerate(self.zData):
            lat = self.maxLat - latIndex * self.latIncrement
            for lonIndex, height in enumerate(row):
                lon = self.minLon + lonIndex * self.lonIncrement
                plotFile.write("{0:.7f} {1:.7f} {2:d}\n".format(lon, lat, height))

    @cache
    def get_contours(
        self,
        step_cont=20,
        max_nodes_per_way=0,
        no_zero=False,
        min_cont=None,
        max_cont=None,
        rdp_epsilon=None,
    ) -> TileContours:
        """Compute tile's contour lines and associated statistics (number of unique nodes and ways).
        Result is cached.

        Args:
            step_cont (int, optional): contours step size. Defaults to 20.
            max_nodes_per_way (int, optional): maximum nodes per way. Defaults to 0.
            no_zero (bool, optional): disable 0 level contour line. Defaults to False.
            min_cont (_type_, optional): minimum contour altitude. Defaults to None.
            max_cont (_type_, optional): maximum contour altitude. Defaults to None.
            rdp_epsilon (_type_, optional): epsilon value for RDP simplification algorithm. Defaults to None.

        Returns:
            TileContours: List of contours coordinates, per elevation, and associates statistics
        """
        elevations, contour_data = self.contourLines(
            step_cont, max_nodes_per_way, no_zero, min_cont, max_cont, rdp_epsilon
        )
        contours_per_elev: Dict[int, List[numpy.ndarray]] = {}
        total_nodes, total_ways = 0, 0
        for elev in elevations:
            contours_per_elev[elev], nb_nodes, nb_ways = contour_data.trace(elev)
            total_nodes += nb_nodes
            total_ways += nb_ways

        tile_contours = TileContours(total_nodes, total_ways, contours_per_elev)
        return tile_contours
