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
