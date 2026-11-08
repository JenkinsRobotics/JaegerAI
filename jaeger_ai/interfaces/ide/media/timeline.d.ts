export {};
declare global {
  var JaegerTimeline: {
    parseSources(data:unknown): Array<{kind:"url"|"file";location:string;title?:string}>;
    parseFollowUps(data:unknown): string[];
    parseSearchCount(data:unknown): {searches:number;completed:number;failed:number}|null;
    parsePlan(data:unknown): Array<{step:string;status:"pending"|"in_progress"|"completed"}>;
    partitionTurn<T extends {kind: string}>(items: T[]): {work: T[]; visible: T[]};
  };
}
