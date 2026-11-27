// Each write completes only after IndexedDB commits. The encrypted vault uses
// optimistic revisions so a stale tab cannot overwrite another tab's entries.
let opening: Promise<IDBDatabase> | undefined;
function database() {
  if (!opening) opening = new Promise<IDBDatabase>((resolve,reject)=>{
    const request=indexedDB.open("jaeger-private-services",1);
    request.onupgradeneeded=()=>{
      request.result.createObjectStore("vault");
      request.result.createObjectStore("activity",{keyPath:"id",autoIncrement:true});
      request.result.createObjectStore("policy");
    };
    request.onerror=()=>{opening=undefined;reject(request.error);};
    request.onsuccess=()=>{
      const db=request.result;
      db.onversionchange=()=>{db.close();opening=undefined;};
      resolve(db);
    };
  });
  return opening;
}
function completed(tx:IDBTransaction) {
  return new Promise<void>((resolve,reject)=>{
    tx.oncomplete=()=>resolve();
    tx.onabort=()=>reject(tx.error ?? new Error("Storage changed in another tab. Reopen and try again."));
    tx.onerror=()=>reject(tx.error);
  });
}
function result<T>(request:IDBRequest<T>) {
  return new Promise<T>((resolve,reject)=>{
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  });
}
export type Contact={kind:"contact";id:string;name:string;address:string;phone:string;email:string};
export type Credential={kind?:"login";id:string; site:string; username:string; password:string};
export type Vault = {revision:number; salt:Uint8Array<ArrayBuffer>; iv:Uint8Array<ArrayBuffer>; ciphertext:ArrayBuffer};
export async function readVault():Promise<Vault|undefined> {
  return result((await database()).transaction("vault").objectStore("vault").get(1));
}
export async function unlockKey(passphrase:string,salt:Uint8Array<ArrayBuffer>) {
  const material=await crypto.subtle.importKey("raw",new TextEncoder().encode(passphrase),"PBKDF2",false,["deriveKey"]);
  return crypto.subtle.deriveKey({name:"PBKDF2",hash:"SHA-256",iterations:600000,salt},material,{name:"AES-GCM",length:256},false,["encrypt","decrypt"]);
}
export async function decryptVault(key:CryptoKey,vault:Vault):Promise<(Credential|Contact)[]> {
  const plain=await crypto.subtle.decrypt({name:"AES-GCM",iv:vault.iv},key,vault.ciphertext);
  return JSON.parse(new TextDecoder().decode(plain));
}
export async function saveVault(key:CryptoKey,salt:Vault["salt"],revision:number,entries:(Credential|Contact)[]) {
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const ciphertext=await crypto.subtle.encrypt({name:"AES-GCM",iv},key,new TextEncoder().encode(JSON.stringify(entries)));
  const db=await database(), tx=db.transaction("vault","readwrite"), done=completed(tx);
  const store=tx.objectStore("vault"), current=store.get(1);
  current.onsuccess=()=>{
    if ((current.result?.revision ?? 0)!==revision) tx.abort();
    else store.put({revision:revision+1,salt,iv,ciphertext},1);
  };
  await done;
}
export type Activity={id:number;at:number;label:string;source:"Jaeger"|"Desktop"};
export type HistoryPolicy={enabled:boolean;paused:boolean;desktop:boolean;indicator:boolean};
const initialPolicy:HistoryPolicy={enabled:false,paused:false,desktop:false,indicator:true};
export async function historyPolicy():Promise<HistoryPolicy>{
  return await result((await database()).transaction("policy").objectStore("policy").get(1)) ?? initialPolicy;
}
export async function changePolicy(change:Partial<HistoryPolicy>){
  const tx=(await database()).transaction("policy","readwrite"),done=completed(tx);
  const store=tx.objectStore("policy"),get=store.get(1);
  get.onsuccess=()=>store.put({...initialPolicy,...get.result,...change},1);
  await done;
  window.dispatchEvent(new Event("jaeger-history-policy"));
}
export async function recordActivity(label:string,source:Activity["source"]){
  const tx=(await database()).transaction(["policy","activity"],"readwrite"),done=completed(tx);
  const policy=tx.objectStore("policy").get(1);
  policy.onsuccess=()=>{
    const p=policy.result;
    if(!p?.enabled || p.paused || (source==="Desktop" && !p.desktop))return;
    const store=tx.objectStore("activity");
    store.add({at:Date.now(),label:label.slice(0,200),source});
    const count=store.count();
    count.onsuccess=()=>{if(count.result>1000){const cursor=store.openCursor();cursor.onsuccess=()=>cursor.result?.delete();}};
  };
  await done;
  window.dispatchEvent(new Event("jaeger-history-updated"));
}
export async function activityList():Promise<Activity[]>{
  return (await result((await database()).transaction("activity").objectStore("activity").getAll())).reverse();
}
export async function clearActivity(id?:number){
  const tx=(await database()).transaction("activity","readwrite"),done=completed(tx);
  const store=tx.objectStore("activity");
  if(id===undefined)store.clear();else store.delete(id);
  await done;window.dispatchEvent(new Event("jaeger-history-updated"));
}
