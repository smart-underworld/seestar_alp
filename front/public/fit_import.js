document.addEventListener('DOMContentLoaded', function() {
    // Ensure DOM is fully loaded
    document.getElementById('getHeaders').addEventListener('click', function() {
        document.getElementById('fileInput').click();
    });

    function getHeaderValue(headerText, keyword) {
        const regex = new RegExp(`${keyword}\\s*=\\s*(\\S+)`);
        const match = headerText.match(regex);
        return match ? match[1].trim() : null;
    }



    document.getElementById('fileInput').addEventListener('change', function(event) {
        const file = event.target.files[0];
        if (!file) return;
        const filename = file.name;
        objectName = filename.split('_')
        const reader = new FileReader();
        reader.onload = function(e) {
            const buffer = e.target.result;
            const headerSize = 2880; // The size of the header in bytes
            const headerBuffer = buffer.slice(0, headerSize);
            const headerText = new TextDecoder("ascii").decode(headerBuffer);
            document.getElementById('targetName').value = objectName[1];
            document.getElementById('ra').value = getHeaderValue(headerText, 'RA');
            document.getElementById('dec').value = getHeaderValue(headerText, 'DEC');
            // document.getElementById('sessionTime').value = getHeaderValue(headerText, 'EXPOSURE').replace('.','s');
            document.getElementById('gain').value = getHeaderValue(headerText,'GAIN');
            document.getElementById('useLpFilter').checked = getHeaderValue(headerText,'FILTER').includes('LP')

        };

        const blob = file.slice(0, 2880);
        reader.readAsArrayBuffer(blob);
    });
});






//
