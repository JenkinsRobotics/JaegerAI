import {act} from "react";
import {createRoot} from "react-dom/client";
import {afterEach,expect,it,vi} from "vitest";
import {fireEvent,within} from "@testing-library/react";
import {ChatOrganizer} from "./ChatOrganizer";
import {MockSource} from "../api/mock";
import type {Organization} from "../api/organization";
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
HTMLDialogElement.prototype.showModal=function(){this.setAttribute("open","");};
let root:ReturnType<typeof createRoot>;
afterEach(async()=>{await act(async()=>root?.unmount());document.body.innerHTML="";});
const flush=async(fn:()=>void=()=>{})=>act(async()=>{fn();await new Promise(r=>setTimeout(r,0));});
async function mount(){
 const state:Organization={revision:0,groups:[],proposals:[],sessions:[{session_id:"a",title:"First chat",workspace:"/original",archived:false},{session_id:"b",title:"Old chat",workspace:"",archived:true}]};
 const command=vi.fn(async(body:Record<string,unknown>)=>{
  if(body.action==="apply"){
   const a=(body.actions as Record<string,unknown>[])[0];
   if(a.type==="rename")state.sessions[0].title=String(a.title);
   if(a.type==="archive")state.sessions.find(s=>s.session_id===(a.session_ids as string[])[0])!.archived=Boolean(a.value);
   state.revision++;return {operation_id:"saved"};
  }
  return {id:"proposal",revision:state.revision,actions:[{type:"rename",session_ids:["a"],title:"Better name"}],label:"AI suggestions"};
 });
 const source=Object.assign(new MockSource(),{organization:{get:vi.fn(async()=>structuredClone(state)),command}});
 const el=document.createElement("div");document.body.append(el);root=createRoot(el);
 const onChanged=vi.fn(async()=>{});
 await flush(()=>root.render(<ChatOrganizer source={source} onClose={()=>{}} onChanged={onChanged} onOpen={()=>{}} onDelete={()=>{}}/>));
 return {command,onChanged,ui:within(el)};
}
it("saves a name through Gateway organization and refreshes",async()=>{
 const {ui,command,onChanged}=await mount();
 await flush(()=>fireEvent.click(ui.getByRole("checkbox",{name:"Select First chat"})));
 await flush(()=>fireEvent.change(ui.getByRole("textbox",{name:"Conversation name"}),{target:{value:"Release plan"}}));
 await flush(()=>fireEvent.click(ui.getByRole("button",{name:"Save name"})));
 expect(command).toHaveBeenCalledWith(expect.objectContaining({action:"apply",revision:0,actions:[{type:"rename",session_ids:["a"],title:"Release plan"}]}));
 expect(ui.getByText("Release plan")).toBeTruthy();
 expect(onChanged).toHaveBeenCalled();
 expect(ui.getByRole("button",{name:"Undo last change"})).toBeTruthy();
});
it("lists archived chats and restores selected history",async()=>{
 const {ui,command}=await mount();
 await flush(()=>fireEvent.click(ui.getByRole("button",{name:"Archived"})));
 await flush(()=>fireEvent.click(ui.getByRole("checkbox",{name:"Select Old chat"})));
 await flush(()=>fireEvent.click(ui.getByRole("button",{name:"Restore"})));
 expect(command).toHaveBeenCalledWith(expect.objectContaining({actions:[{type:"archive",session_ids:["b"],value:false}]}));
 expect(ui.queryByRole("checkbox",{name:"Select Old chat"})).toBeNull();
});
it("shows AI proposal before allowing application",async()=>{
 const {ui,command}=await mount();
 await flush(()=>fireEvent.click(ui.getByRole("checkbox",{name:"Select First chat"})));
 await flush(()=>fireEvent.click(ui.getByRole("button",{name:"AI name"})));
 expect(command).toHaveBeenCalledTimes(1);
 expect(command.mock.calls[0][0].action).toBe("suggest");
 expect(ui.getByText("First chat → Better name")).toBeTruthy();
 await flush(()=>fireEvent.click(ui.getByRole("button",{name:"Apply suggestions"})));
 expect(command).toHaveBeenCalledWith(expect.objectContaining({action:"apply",actions:[{type:"rename",session_ids:["a"],title:"Better name"}]}));
});
