function n(e){let t=e.get("q");if(!t)return null;try{return JSON.parse(decodeURIComponent(atob(t)))}catch(e){return console.error("Error decoding search query:",e),null}}
