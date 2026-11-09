export type OrganizationAction = {type: string; [key: string]: unknown};
export interface ChatGroup {id: string; name: string; kind: "project"|"section"; notes: string}
export interface OrganizedChat {session_id:string; title:string; workspace:string; archived:boolean; pinned?:boolean; manual_title?:boolean; project_id?:string|null; section_id?:string|null; position?:number}
export interface OrganizationProposal {id:string; label:string; revision:number; actions:OrganizationAction[]}
export interface Organization {revision:number; groups:ChatGroup[]; sessions:OrganizedChat[]; proposals:OrganizationProposal[]}
export interface OrganizationResult {operation_id?:string; id?:string; label?:string; revision?:number; actions?:OrganizationAction[]}
