export type OrganizationAction = {type: string; [key: string]: unknown};
export interface ChatGroup {id: string; name: string; kind: "project"|"section"; notes: string}
export interface OrganizedChat {session_id:string; title:string; workspace:string; archived:boolean; pinned?:boolean; manual_title?:boolean; title_source?:string; project_id?:string|null; section_id?:string|null; position?:number; kind?:string; home_session_id?:string; start_message_id?:number; end_message_id?:number|null; message_count?:number; updated_at?:number}
export interface OrganizationProposal {id:string; label:string; revision:number; actions:OrganizationAction[]}
export interface Organization {revision:number; groups:ChatGroup[]; sessions:OrganizedChat[]; proposals:OrganizationProposal[]}
export interface OrganizationResult {operation_id?:string; id?:string; label?:string; revision?:number; actions?:OrganizationAction[]}
