/** Device-local opt-in only; reading server diagnostics never enables reporting. */
export const DIAGNOSTIC_CAPTURE_KEY='jaeger.ui.diagnostics.active.v1';
export interface DiagnosticCaptureSnapshot {
 boot_id:string;scope:string;max_events:number;max_seconds:number;codes:Record<string,string>;retention:string;
 capture:null|{id:string;operation_id:string;state:'active'|'expired'|'stopped';started_at:number;expires_at:number;duration_seconds:number;occurrences:number;unique_receipts:number;overflow_occurrences:number;saturated:boolean};
 events:{receipt_ref:string;stage:string;code:string;session_ref:string|null;request_ref:string|null;occurrences:number}[];
}
export interface DiagnosticCaptureControls {
 read():Promise<DiagnosticCaptureSnapshot>;
 start(body:{operation_id:string;duration_seconds:number}):Promise<DiagnosticCaptureSnapshot>;
 stop(id:string):Promise<DiagnosticCaptureSnapshot>;
 export():Promise<DiagnosticCaptureSnapshot&{format:string}>;
}
export function enableDiagnosticReporting(snapshot:DiagnosticCaptureSnapshot){
 const c=snapshot.capture;
 if(c?.state==='active')localStorage.setItem(DIAGNOSTIC_CAPTURE_KEY,JSON.stringify({id:c.id,boot_id:snapshot.boot_id,expires_at:c.expires_at}));
 else localStorage.removeItem(DIAGNOSTIC_CAPTURE_KEY);
}
