document.addEventListener('DOMContentLoaded', function() {
    // Ensure DOM is fully loaded
    document.getElementById('getHeaders').addEventListener('click', function() {
        document.getElementById('fileInput').click();
    });


    document.getElementById('fileInput').addEventListener('change', function(event) {
        const file = event.target.files[0];
        const reader = new FileReader();

        reader.onload = function(e) {
            const buffer = e.target.result;
            processFITSHeader(buffer);
        };

        reader.readAsArrayBuffer(file);
    });

    function processFITSHeader(buffer) {
        const bytes = new Uint8Array(buffer);

        // Iterate over the buffer in 80-byte chunks (one card at a time)
        for (let i = 0; i < bytes.length; i += 80) {
            const card = bytes.slice(i, i + 80); // Read 80-byte card
            const cardString = new TextDecoder().decode(card); // Convert to string

            const keyword = cardString.slice(0, 8).trim(); // Extract keyword
            let value = cardString.slice(10, 70).trim(); // Extract from position 10 to 70
            const splitValue = value.split('/');
            value = splitValue[0].trim();
            if (value.startsWith("'")) {
                const match = value.match(/'(.*?)'/);
                if (match) {
                    value = match[1].trim(); // Get the content between the quotes
                }
            }
            // Check for specific keywords (optional, just for processing)
            if (keyword === 'RA') {
                document.getElementById('ra').value = value
            }
            if (keyword === 'DEC') {
                document.getElementById('dec').value = value
            }
            if (keyword === 'OBJECT') {
                document.getElementById('targetName').value = value
            }
            if (keyword === 'FILTER') {
                if (value === 'LP') {
                    document.getElementById('useLpFilter').checked = true
                } else {
                    document.getElementById('useLpFilter').checked = false
                }
            }
            // Stop if END keyword is found
            if (keyword === 'END') {
                break;
            }
        }

    }

});






//
