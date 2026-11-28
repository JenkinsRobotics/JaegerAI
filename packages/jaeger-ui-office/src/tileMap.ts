/**
 * 4-connected BFS tile-map pathfinding adapted from pixel-agents-hq/pixel-agents (MIT).
 */
import { TileType } from "./types";

export interface GridPoint {
  col: number;
  row: number;
}

export function isWalkable(
  col: number,
  row: number,
  tileMap: TileType[][],
  blockedTiles: Set<string>,
): boolean {
  const rows = tileMap.length;
  const cols = rows > 0 ? tileMap[0].length : 0;
  if (row < 0 || row >= rows || col < 0 || col >= cols) return false;
  const t = tileMap[row][col];
  if (t === TileType.WALL || t === TileType.VOID) return false;
  if (blockedTiles.has(`${col},${row}`)) return false;
  return true;
}

export function getWalkableTiles(
  tileMap: TileType[][],
  blockedTiles: Set<string>,
): GridPoint[] {
  const rows = tileMap.length;
  const cols = rows > 0 ? tileMap[0].length : 0;
  const tiles: GridPoint[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (isWalkable(c, r, tileMap, blockedTiles)) {
        tiles.push({ col: c, row: r });
      }
    }
  }
  return tiles;
}

export function findPath(
  startCol: number,
  startRow: number,
  endCol: number,
  endRow: number,
  tileMap: TileType[][],
  blockedTiles: Set<string>,
): GridPoint[] {
  if (startCol === endCol && startRow === endRow) return [];
  if (!isWalkable(endCol, endRow, tileMap, blockedTiles)) return [];

  const key = (c: number, r: number) => `${c},${r}`;
  const startKey = key(startCol, startRow);
  const endKey = key(endCol, endRow);

  const visited = new Set<string>([startKey]);
  const parent = new Map<string, string>();
  const queue: GridPoint[] = [{ col: startCol, row: startRow }];
  const dirs = [
    { dc: 0, dr: -1 },
    { dc: 0, dr: 1 },
    { dc: -1, dr: 0 },
    { dc: 1, dr: 0 },
  ];

  while (queue.length > 0) {
    const curr = queue.shift()!;
    const currKey = key(curr.col, curr.row);
    if (currKey === endKey) {
      const path: GridPoint[] = [];
      let k = endKey;
      while (k !== startKey) {
        const [c, r] = k.split(",").map(Number);
        path.unshift({ col: c, row: r });
        k = parent.get(k)!;
      }
      return path;
    }
    for (const d of dirs) {
      const nc = curr.col + d.dc;
      const nr = curr.row + d.dr;
      const nk = key(nc, nr);
      if (visited.has(nk)) continue;
      if (!isWalkable(nc, nr, tileMap, blockedTiles)) continue;
      visited.add(nk);
      parent.set(nk, currKey);
      queue.push({ col: nc, row: nr });
    }
  }
  return [];
}
