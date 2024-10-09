let currentForm;

function showModal(event, form) {
    event.preventDefault();

    const outputAlert = document.getElementById('outputAlert');
    if (outputAlert) {
        outputAlert.innerHTML = '';
    }

    currentForm = form;
    const dropdown = form.querySelector('select[name="command"]');
    const commandInput = form.querySelector('input[name="command"]');
    let selectedText;

    if (dropdown) {
        selectedText = dropdown.options[dropdown.selectedIndex].text;
    } else if (commandInput && commandInput.value === "start_up_sequence") {
        selectedText = "Start-Up Sequence";
    } else {
        selectedText = "Command Execution";
    }

    document.getElementById('selectedCommandText').textContent = selectedText;

    if (confirm) {
        const modal = new bootstrap.Modal(document.getElementById('confirmationModal'));
        modal.show();

        document.getElementById('confirmButton').onclick = function() {
            modal.hide();
            currentForm.submit();
        };
    } else {
        currentForm.submit();
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const eventStatusDiv = document.getElementById('eventStatusDiv');
    const eventStatusContent = document.getElementById('eventStatusContent');

    eventStatusDiv.addEventListener('hide.bs.collapse', function () {
        console.log('Accordion collapsed');
		eventStatusContent.setAttribute('hx-disable', '');
    });

    eventStatusDiv.addEventListener('show.bs.collapse', function () {
        console.log('Accordion expanded');
		eventStatusContent.removeAttribute('hx-disable');
		htmx.trigger(eventStatusContent, 'htmx:load');
    });
});
