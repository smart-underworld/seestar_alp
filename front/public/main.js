// main source code

async function fetchCoordinates() {
    switch (document.getElementById('searchFor').value){
        // Local Deepsky Search
        case 'LS':
            if (document.getElementById('targetName').value == '') {
                alert('You must supply a target name to be looked up in local database');
                return;
            }
            target = document.getElementById('targetName').value;
            queryURL = '/localsearch?target=' + target
            fetch(queryURL)
            .then(response => {
                if (!response.ok) {
                    if (response.statusText = "Internal SerInternal Server Error") {
                        alert("Object " + document.getElementById('targetName').value + " not found!" )
                        return;
                    } else {
                        alert('There is an issue contacting local server');
                    }
                    throw new Error('Network response was not ok ' + response.statusText);
                }
                return response.text();
            })
            .then(data => {
                // Only proess if object data sent back
                if (data){
                    objects = JSON.parse(data);
                    if (objects.length > 1) {
                        openItemModal(objects, 'objectName').then(selectedObject => {
                            document.getElementById('ra').value = selectedObject.ra;
                            document.getElementById('dec').value = selectedObject.dec;
                            document.getElementById("useJ2000").checked = true;
                            document.getElementById("useLpFilter").checked = (selectedObject.lp === 'true');
                            if (selectedObject.name != '') {
                                document.getElementById("targetName").value = selectedObject.objectName;
                            };
                        });
                    } else {
                        selectedObject = objects[0];
                        document.getElementById('ra').value = selectedObject.ra;
                        document.getElementById('dec').value = selectedObject.dec;
                        document.getElementById("useJ2000").checked = true;
                        document.getElementById("useLpFilter").checked = (selectedObject.lp === 'true');
                        if (selectedObject.name != '') {
                            document.getElementById("targetName").value = selectedObject.objectName;
                        };
                    }
                };
            });
            break;

        // Deepsky
        case 'DS':
            if (document.getElementById('targetName').value == '') {
                alert('You must supply a target name to be looked up in Simbad');
                return;
            }
            // compose the url to retreive the data from the server
            const baseURL =
                `${window.location.protocol}//${window.location.hostname}${window.location.port ? ':' + window.location.port : ''}`;
            simbadURL = baseURL + '/simbad?name=' + encodeURIComponent(document.getElementById('targetName').value);
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
                document.getElementById('useLpFilter').checked = false;
                if (elements[2] == 'on')
                    document.getElementById('useLpFilter').checked = true;
            })
            .catch(error => console.error('There was a problem with the fetch operation:', error));
            break;

        // Planet
        case 'PL':
            if (document.getElementById('targetName').value == '') {
                alert('You must supply a planet name to be looked up');
                return;
            }
            // Grab request text
            planet = document.getElementById('targetName').value;
            queryURL = '/getplanetcoordinates?planetname=' + planet;
            // Moon / Sun doesn't have 'BARYCENTER' after it but more checks needed for Sun first so just do Moon
            if (planet.toLowerCase() != 'moon') {queryURL += " BARYCENTER"};
            fetch(queryURL)
            .then(response => {
                if (!response.ok) {
                    if (response.statusText = "Internal SerInternal Server Error") {
                        alert("Planet " + document.getElementById('targetName').value + " not found!" )
                        return;
                    } else {
                        alert('There is an issue contacting planet server');
                    }
                    throw new Error('Network response was not ok ' + response.statusText);
                }
                return response.text();
            })
            .then(data => {
                // data should come back in the form of 05h 18m 48.04s, +22deg 23' 10.8"
                data = data.replace(/\s/g, '');
                data = data.replace("deg","d");
                data = data.replace("'","m");
                data = data.replace('"', "s");
                const elements = data.trim().split(",");
                document.getElementById('ra').value = elements[0];
                document.getElementById('dec').value = elements[1];
                document.getElementById("useJ2000").checked = false
            })
            break;

        // Minor Planet (Asteroid)
        case 'MP':
            // Check for valid query info
            if (document.getElementById('targetName').value == '') {
                alert('You must supply a planet name to be looked up');
                return;
            }
            minorname = document.getElementById('targetName').value;
            queryURL = '/getminorplanetcoordinates?minorname=' + minorname;
            fetch(queryURL)
            .then(response => {
                // If a server error or object not found
                if (!response.ok) {
                    if (response.statusText = "Not Found") {
                        alert("Minor planet " + document.getElementById('targetName').value + " not found!" )
                        return;
                    } else {
                        alert('There is an issue contacting the server');
                    }clearInterval
                    throw new Error('Network response was not ok ' + response.statusText);
                }
                return response.text();
            })
            .then(data => {
                // Only proess if object data sent back
                if (data){
                    elements = JSON.parse(data)

                    document.getElementById('ra').value = elements.ra;
                    document.getElementById('dec').value = elements.dec;
                    document.getElementById("useJ2000").checked = true;
                    document.getElementById('useLpFilter').checked = false;
                };
            });
            break;

        // Comet
        case 'CO':
            if (document.getElementById('targetName').value == '') {
                alert('You must supply a planet name to be looked up');
                return;
            }
            cometname = document.getElementById('targetName').value;
            queryURL = '/getcometcoordinates?cometname=' + cometname;
            fetch(queryURL)
            .then(response => {
                // If a server error or object not found
                if (!response.ok) {
                    if (response.statusText = "Not Found") {
                        alert("Comet " + document.getElementById('targetName').value + " not found!" )
                        return;
                    } else {
                        alert('There is an issue contacting the server');
                    }
                    throw new Error('Network response was not ok ' + response.statusText);
                }
                return response.text();
            })
            .then(data => {
                // Only proess if object data sent back
                if (data){
                    cometData = JSON.parse(data);
                    if (cometData.length > 1) {
                        openItemModal(cometData, 'cometName').then(selectedComet => {
                            document.getElementById('ra').value = selectedComet.ra;
                            document.getElementById('dec').value = selectedComet.dec;
                            document.getElementById('targetName').value = selectedComet.cometName;
                            document.getElementById("useJ2000").checked = true;
                            document.getElementById('useLpFilter').checked = false;
                        });
                    } else {
                        document.getElementById('ra').value = cometData.ra;
                        document.getElementById('dec').value = cometData.dec;
                        document.getElementById('targetName').value = cometData.cometName;
                        document.getElementById("useJ2000").checked = true;
                        document.getElementById('useLpFilter').checked = false;
                    };

                };
            });
        break;

        // Variable Star
        case 'VS':
            if (document.getElementById('targetName').value == '') {
                alert('You must supply a planet name to be looked up');
                return;
            }
            starName = document.getElementById('targetName').value;
            queryURL = '/getaavsocoordinates?target=' + starName;
            fetch(queryURL)
            .then(response => {
                // If a server error or object not found
                if (!response.ok) {
                    if (response.statusText = "Not Found") {
                        alert("Variable star " + document.getElementById('targetName').value + " not found!" )
                        return;
                    } else {
                        alert('There is an issue contacting the server');
                    }
                    throw new Error('Network response was not ok ' + response.statusText);
                }
                return response.text();
            })
            .then(data => {
                // Only proess if object data sent back
                if (data){
                    starData = JSON.parse(data);
                        document.getElementById('ra').value = starData["ra"];
                        document.getElementById('dec').value = starData["dec"];
                        document.getElementById("useJ2000").checked = true;
                        document.getElementById('useLpFilter').checked = false;
                    };
            });
        break;
    }
};

async function fetchClipboard() {
    try {
        // get the data from the clipboard
        const text = await navigator.clipboard.readText();

        // Split the input string into an array using space as the separator
        const elements = text.trim().split(/[\s,]+/);   // Telescopious has a comma in the coordinates
        // Check that there are exactly 6 elements
        if (elements.length == 6) {  // astro mosaic, telescopious from csv file, Mosaic Planner
            // Format RA and DEC
            ra = `${elements[0]}h${elements[1]}m${elements[2]}s`;
            dec = `${elements[3]}d${elements[4]}m${elements[5]}s`;

            ra = ra.replace("hr","").replace(/[^a-zA-Z0-9.]/g, "");
            dec = dec.replace(/[^a-zA-Z0-9.]/g, "");

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
        console.log(data);
        elements = JSON.parse(data);
        document.getElementById('targetName').value = elements.name;
        document.getElementById('ra').value = elements.ra;
        document.getElementById('dec').value = elements.dec;
        document.getElementById('useJ2000').checked = true;
        document.getElementById('useLpFilter').checked = elements.lp;
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

function get_location_from_browser() {
    // This doesn't work as SSC doesn't use HTTPS
    function success(position) {
        const latitude = position.coords.latitude;
        const longitude = position.coords.longitude;

        document.getElementById('Latitude').value = latitude;
        document.getElementById('Longitude').value = longitude;
    }

    function error(err) {
        alert("Unable to get location from browser.");
        console.warn(`ERROR(${err.code}): ${err.message}`);
    }

    if (!navigator.geolocation) {
        alert("Geolocation is not supported by your browser");
    } else {
        navigator.geolocation.getCurrentPosition(success, error, {maximumAge:60000, timeout:2000, enableHighAccuracy:true});
    }
}

async function get_location_from_IP() {
    const url = "https://ipapi.co/json/";

    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Response status: ${response.status}`);
        }

        const json = await response.json();
        const latitude = json['latitude'];
        const longitude = json['longitude'];

        document.getElementById('Latitude').value = latitude;
        document.getElementById('Longitude').value = longitude;
        console.log("Latitude: " + latitude + " Longitude: " + longitude);
    } catch (error) {
        console.error(error.message);
    }
}

let selectedItem = null;

// Function to open the modal and populate the item list
function openItemModal(items, displayProperty, callback) {
    return new Promise((resolve) => {
        const itemList = document.getElementById("itemList");  // Update to generic list ID
        const modal = new bootstrap.Modal(document.getElementById('itemModal'));  // Update to generic modal ID

        itemList.innerHTML = '';

        items.forEach(item => {
            const li = document.createElement('li');
            li.classList.add('list-group-item', 'list-group-item-action');
            li.textContent = item[displayProperty];  // Display chosen property of item
            li.addEventListener('click', () => {
                selectedItem = item;
                resolve(selectedItem);  // Resolve with the selected item
                modal.hide();
                if (callback) callback(item);  // Call the callback function if provided
            });
            itemList.appendChild(li);
        });

        modal.show();
    });
}

// Example callback function to handle selected item properties
function handleItemSelection(item) {
    document.getElementById('ra').value = item.ra || '';
    document.getElementById('dec').value = item.dec || '';
    document.getElementById('targetName').value = item.name || '';  // Use 'name' or other fields
    document.getElementById('useLpFilter').checked = false;
    document.getElementById("useJ2000").checked = true;
}

function addSeestar(){
    var devicecount = document.getElementsByName('ss_name').length + 1; //parseInt(document.getElementById('devicecount') + 1);
    var lastElement = document.getElementById(`device_div_${devicecount - 1}`);

    var insertBlock = `<div id="device_div_${devicecount}">
                            <div class="col-sm-4 text-end">
                                <label class="form-label">
                                    <h3>Device number ${devicecount}</h3>
                                </label>
                            </div>
                            <div class="row mb-3 align-items-center">
                                <!-- Row -->
                                <div class="col-sm-4 text-end">
                                    <!-- Col -->
                                    <label for="ss_name" class="form-label">Name</label>
                                </div>
                                <!-- Close Col -->
                                <div class="col-sm-8 col-md-6">
                                    <!-- Col -->
                                    <input id="ss_name" name="ss_name" type="text" class="form-control" title="" value="" required>
                                </div>
                                <!-- Close Col -->
                            </div>
                            <!-- Close Row -->
                            <div class="row mb-3 align-items-center">
                                <!-- Row -->
                                <div class="col-sm-4 text-end">
                                    <!-- Col -->
                                    <label for="ss_ip_address" class="form-label">IP Address</label>
                                </div>
                                <!-- Close Col -->
                                <div class="col-sm-8 col-md-6">
                                    <!-- Col -->
                                    <input id="ss_ip_address" name="ss_ip_address" type="text" class="form-control" title="" value="" required>
                                </div>
                                <!-- Close Col -->
                            </div>
                            <!-- Close Row -->
                            <input id="ss_is_EQ_mode_hidden_${devicecount}" name="ss_is_EQ_mode" type="hidden" value="False">
                            <div class="row mb-3 align-items-center">
                                <!-- Checkbox Row -->
                                <div class="col-sm-4 text-end">
                                    <!-- Checkbox label -->
                                    <label for="ss_is_EQ_mode_${devicecount}" class="form-label">
                                    Is device in EQ mode
                                    </label>
                                </div>
                                <!-- Close checkbox label -->
                                <div class="col-sm-8 col-md-6">
                                    <!-- Checkbox -->
                                    <input id="ss_is_EQ_mode_${devicecount}" class="form-check-input" title="Is device in EQ mode" type="checkbox" onclick="NewCheckboxChange('ss_is_EQ_mode_hidden_${devicecount}')">
                                </div>
                                <!--Close checkbox -->
                            </div>
                            <!-- Close checkbox row -->
                            <div class="row mb-3 align-items-center">
                                <!-- Checkbox Row -->
                                <div class="col-sm-4 text-end">
                                    <!-- Checkbox label -->
                                    <label for="delete_${devicecount}" class="form-label">
                                    Delete device
                                    </label>
                                </div>
                                <!-- Close checkbox label -->
                                <div class="col-sm-8 col-md-6">
                                    <!-- Checkbox -->
                                    <input id="delete_${devicecount}" name="delete_${devicecount}" class="form-check-input" title="" type="checkbox" >
                                </div>
                                <!--Close checkbox -->
                            </div>
                            <!-- Close checkbox row -->
                        </div>
                            `;
    lastElement.insertAdjacentHTML('afterend', insertBlock);
}


function NewCheckboxChange(element) {
    hidden = document.getElementById(element);
    if (hidden.value == "True") {
        hidden.value = "False";
    } else {
        hidden.value = "True";
     }
};

function delSeestar() {
    // Get all the checkboxes
    var elements = document.querySelectorAll('[id^=delete_]');
    for (const cb of elements) {
        if (cb.checked == true) {
            var number = cb.name.split('_')[1];
            var deviceDiv = document.getElementById('device_div_' + number);
            deviceDiv.remove(deviceDiv);
        }
    }

}

// Create event listener to monitor the seestar checkboxes.  Upon change of the checkbox state,
// update the associated hidden checkbox with True / False so we have somthing to send back upon unchecked.

document.querySelectorAll('[id^=ss_is_EQ_mode_]:not([id^=is_EQ_mode_hidden_])').forEach(function(element) {
    element.addEventListener('change', function(event) {
        // Directly access the changed element
        var changedElement = event.target;
        var elementNumber = changedElement.id.split("_").pop();
        var hiddenInput = document.getElementById('ss_is_EQ_mode_hidden_' + elementNumber);

        // Correctly update the hidden input value
        hiddenInput.value = changedElement.checked ? 'True' : 'False';
    });
});


