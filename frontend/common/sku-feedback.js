(() => {
  const root=document.createElement('aside');root.className='sku-feedback';
  root.setAttribute('aria-label','Notifications');
  function card(kind){
    const box=document.createElement('section');box.className='sku-feedback-card '+kind;box.hidden=true;
    const title=document.createElement('strong'),text=document.createElement('p');
    const content=document.createElement('div');content.append(title,text);box.append(content);root.append(box);
    return {box,title,text};
  }
  const progress=card('sku-feedback-progress'),notice=card('sku-feedback-notice');
  progress.box.setAttribute('role','status');progress.box.setAttribute('aria-live','polite');
  const spinner=document.createElement('span');spinner.className='sku-feedback-spinner';spinner.setAttribute('aria-hidden','true');progress.box.append(spinner);
  const close=document.createElement('button');close.type='button';close.className='sku-feedback-close';close.textContent='\u00d7';close.setAttribute('aria-label','Dismiss notification');
  close.onclick=()=>{notice.box.hidden=true;};notice.box.append(close);
  document.body.append(root);
  const pending=new Map();
  function updateProgress(){
    const active=[...pending.values()].at(-1);progress.box.hidden=!active;
    progress.box.setAttribute('aria-busy',String(Boolean(active)));
    if(active){progress.title.textContent=active.title;progress.text.textContent=active.reason;}
  }
  function loading(title,reason){
    notice.box.hidden=true;
    const token={};pending.set(token,{title,reason});updateProgress();
    return ()=>{pending.delete(token);updateProgress();};
  }
  window.skuFeedback={
    show(text,error=false){
      notice.box.hidden=!text;notice.box.className='sku-feedback-card sku-feedback-notice'+(error?' sku-feedback-error':'');
      notice.box.setAttribute('role',error?'alert':'status');
      notice.title.textContent=error?'Action needed':'Update';notice.text.textContent=text;
    },
    loading,
    startRequest(path,options={}){
      if(/\/sku-lookup(?:$|\?)/.test(path))return loading('Looking up SKU details','Fetching product details, prices and available quantities. Please wait.');
      if(path==='/api/sku-defaults')return loading('Loading item defaults','Fetching the configured HSN code for your manual SKU.');
      const saving=['POST','PUT'].includes(options.method);
      const lineSave=/\/lines(?:\/\d+|\/bulk)?$/.test(path);
      let draftSave=false;
      if(saving&&/^\/api\/(orders|enquiries)$/.test(path)){
        try{draftSave=Boolean(JSON.parse(options.body||'{}').lines?.length);}catch(_){/* Request validation handles invalid bodies. */}
      }
      if(saving&&(lineSave||draftSave))return loading('Checking stock before saving','Looking up current stock for each SKU and comparing it with the requested quantity. Your items will be saved after the check passes.');
      return ()=>{};
    }
  };
})();
