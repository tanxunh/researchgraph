import { useCallback, useEffect, useState } from 'react';
export function useResource(load, pollDelay, revalidateOnFocus = false) {
  const [state,setState]=useState({data:null,loading:true,error:null});
  const [revision,setRevision]=useState(0);
  const refresh=useCallback(()=>setRevision(n=>n+1),[]);
  useEffect(()=>{
    let alive=true,timer,controller,lastStarted=0;
    setState(old=>({...old,loading:true,error:null}));
    async function run(){
      if(!alive||controller)return;
      lastStarted=Date.now();
      controller=new AbortController();
      try {
        const data=await load(controller.signal);if(!alive)return;
        setState({data,loading:false,error:null});
        const delay=pollDelay?.(data);if(delay)timer=setTimeout(()=>{if(!document.hidden)run();},delay);
      }catch(error){if(alive)setState(old=>({...old,loading:false,error}));}
      finally{controller=null;}
    }
    function visible(){if(!document.hidden){clearTimeout(timer);run();}}
    function focused(){
      if(!document.hidden && Date.now()-lastStarted>=1000){clearTimeout(timer);run();}
    }
    if(pollDelay)document.addEventListener('visibilitychange',visible);
    if(revalidateOnFocus)window.addEventListener('focus',focused);
    run();return()=>{alive=false;clearTimeout(timer);controller?.abort();if(pollDelay)document.removeEventListener('visibilitychange',visible);if(revalidateOnFocus)window.removeEventListener('focus',focused);};
  },[load,pollDelay,revision,revalidateOnFocus]);
  return {...state,refresh};
}
