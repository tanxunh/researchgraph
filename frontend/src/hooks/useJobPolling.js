import { useEffect, useRef, useState } from 'react';
import { activeJob, libraryApi } from '../api/library';
// One owner per uploaded job. Jobs workspace uses list polling instead.
export function useJobPolling(jobId, onTerminal) {
  const [job,setJob]=useState(null),[error,setError]=useState(null),[revision,setRevision]=useState(0);
  const callback=useRef(onTerminal);callback.current=onTerminal;
  const notified=useRef(null);
  useEffect(()=>{
    let alive=true,timer,controller,stopped=false;
    setJob(null);setError(null);
    async function poll(){
      if(!alive||stopped||controller||document.hidden)return;
      clearTimeout(timer);controller=new AbortController();
      try {
        const value=await libraryApi.job(jobId,{signal:controller.signal});
        if(!alive)return;setJob(value);setError(null);
        if(activeJob(value)) timer=setTimeout(poll,1800);
        else {stopped=true;if(notified.current!==jobId){notified.current=jobId;callback.current?.(value);}}
      }catch(e){if(alive){setError(e);stopped=true;}}
      finally{controller=null;}
    }
    function visibility(){if(!document.hidden)poll();else clearTimeout(timer);}
    document.addEventListener('visibilitychange',visibility);poll();
    return()=>{alive=false;clearTimeout(timer);controller?.abort();document.removeEventListener('visibilitychange',visibility);};
  },[jobId,revision]);
  return {job,error,refresh:()=>setRevision(n=>n+1)};
}
