export {};
declare global {
  var JaegerTimeline: {
    partitionTurn<T extends {kind: string}>(items: T[]): {work: T[]; visible: T[]};
  };
}
