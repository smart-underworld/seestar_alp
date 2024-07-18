// main source code

async function fetchSimbad() {
    if (document.getElementById('targetName').value == '') {
        alert('You must supply a target name to be looked up in Simbad');
        return;
    }
    // compose the url to retreive the data from the server
    const baseURL = 
         `${window.location.protocol}//${window.location.hostname}${window.location.port ? ':' + window.location.port : ''}`;
    simbadURL = baseURL + '/simbad?name=' + document.getElementById('targetName').value;
    // fetch the data
    fetch(simbadURL)
    .then(response => {
        if (!response.ok) {
            if (response.statusText == 'Not Found') {
                alert("Target Not Found")
                return;
            } else {
                alert('There is an issue contacting Simbad');
            }
            throw new Error('Network response was not ok ' + response.statusText);
        }
        return response.text();
    })
    .then(data => {
        // data should come back in the form of 'ra dec'
        const elements = data.trim().split(/\s+/);
        document.getElementById('ra').value = elements[0];
        document.getElementById('dec').value = elements[1];
        document.getElementById("useJ2000").checked = true;
    })
    .catch(error => console.error('There was a problem with the fetch operation:', error));

}

async function fetchClipboard() {
    try {
        // get the data from the clipboard
        const text = await navigator.clipboard.readText();

        // Split the input string into an array using space as the separator
        const elements = text.trim().split(/\s+/);
        // Check that there are exactly 6 elements
        if (elements.length == 6) {  // astro mosaic
            // Format RA and DEC
            const ra = `${elements[0]}h${elements[1]}m${elements[2]}s`;
            const dec = `${elements[3]}d${elements[4]}m${elements[5]}s`;

            document.getElementById('ra').value = ra;
            document.getElementById('dec').value = dec;
        } else if (elements.length == 2 ) {
            ra  = elements[0].replace("δ:","");   // astro-bin format

            dec = elements[1].replace("°","d"); 
            dec = dec.replace("'","m");
            dec = dec.replace('"',"s");
            dec = dec.replace("DE:","");   // Cartes du Ciel puts a DE: in the string
            document.getElementById('ra').value = ra;
            document.getElementById('dec').value = dec;
        } else if (elements.length == 8 ) {       // Telescopious     RA 0hr 42' 44", DEC 41° 15' 58"
            ra = `${elements[1]}${elements[2]}${elements[3]}`;
            dec = `${elements[5]}${elements[6]}${elements[7]}`;
            ra  = ra.replace("hr","h");   // Telescopious format
            ra = ra.replace("'","m");
            ra = ra.replace('"',"s");
            ra = ra.replace(',',"");

            dec = dec.replace("°","d"); 
            dec = dec.replace("'","m");
            dec = dec.replace('"',"s");
            document.getElementById('ra').value = ra;
            document.getElementById('dec').value = dec;

        } else {
            alert('Failed to parse clipboard contents:' + text);

        }

    } catch (err) {
        alert('Failed to read clipboard contents');
    }
}

async function fetchStellarium() {
try {
    const baseURL = 
         `${window.location.protocol}//${window.location.hostname}${window.location.port ? ':' + window.location.port : ''}`;
    stellariumURL = baseURL + '/stellarium';
    fetch(stellariumURL)
    .then(response => {
        if (!response.ok) {
            if (response.statusText == 'Not Found') {
                alert("There was a problem communicating with Stellarium")
                return;
            } else {
                alert('Failed to read from Stellarium');
            }                
            throw new Error('Network response was not ok ' + response.statusText);
        }
        return response.text();
    })
    .then(data => {
        const elements = data.trim().split("/");
        document.getElementById('ra').value = elements[0];
        document.getElementById('dec').value = elements[1];
    })
    .catch(error => console.error('There was a problem with the fetch operation:', error));

} catch(err) {
    console.error('Failed to read from Stellarium', err);
}
}

async function toggleuitheme() {
    //update the current page
    if (document.documentElement.getAttribute('data-bs-theme') == 'dark') {
        document.documentElement.setAttribute('data-bs-theme','light')
    } else {
        document.documentElement.setAttribute('data-bs-theme','dark')
    }
    
    //update the config
    try{
        const baseURL = 
         `${window.location.protocol}//${window.location.hostname}${window.location.port ? ':' + window.location.port : ''}`;
        toggleuithemeURL = baseURL + '/toggleuitheme';
        fetch(toggleuithemeURL)
    } catch(err) {
        console.error('Failed to toggle ui theme', err);
    }
}