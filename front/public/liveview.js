function updateModeButtons(mode) {
    // console.log('updateModeButtons')
    const buttons = document.getElementsByClassName("mode-button");
    for (const el of buttons) {
        // console.log('looking at id', el.id)
        if (el.id === mode) {
            el.classList.add('btn-primary');
            el.classList.remove('btn-secondary');
        } else {
            el.classList.remove('btn-primary');
            el.classList.add('btn-secondary');
        }
    }
}

function updateMovementControls(stage) {
    // console.log('updateMovementControls', stage);
    const el = document.getElementById('movement-controls')
    if (el) {
        if (stage === 'Stack') {
            el.classList.add('visually-hidden')
        } else {
            el.classList.remove('visually-hidden')
        }
    }
}

// document.body.addEventListener("statusUpdate", function (evt) {
//     const mode = evt.detail.mode;
//     const stage = evt.detail.stage;
//     console.log("status update")
//     updateModeButtons(mode);
//     updateMovementControls(stage);
// })
//
// document.body.addEventListener("liveViewModeChange", function (evt) {
//     evt.detail.value is mode
// const mode = evt.detail.value;
// console.log(`liveViewModeChange was triggered! mode=${mode}`);
// const img = document.getElementById('liveViewImg');
// let currentSrc = "{{ imager_root }}/vid";
// Add a cache-busting parameter
// if (currentSrc.indexOf('?') > -1) {
//     currentSrc = currentSrc.substring(0, currentSrc.indexOf('?'));
// }
// const newSrc = currentSrc + "?timestamp=" + new Date().getTime();
//
// img.src = newSrc;
//
// updateModeButtons(mode);
// })
//
//

class LiveViewJoystick {
    constructor(rootPath, elementId) {
        const options = {
            zone: document.getElementById(elementId),
            color: 'red',
            position: {left: '50%', top: '50%'},
            mode: 'static',
            dynamicPage: true,
        }
        this.joystick = nipplejs.create(options);
        this.rootPath = rootPath;

        this.zero_vector = {angle: 0, distance: 0, force: 0};
        this.timer = -1;
        this.vector = this.zero_vector;
        this.positionEl = document.getElementById('position');
    }

    #sendMove() {
        fetch(this.rootPath + '/position', {
            method: 'POST',
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(this.vector)
        })
            .then(response => response.text())
            .then(body => {
                console.log('response:', body)
                //this.positionEl.innerHTML = body;
            });
    }

    register() {
        const self = this;
        this.joystick.on('move', function (evt, data) {
            self.vector = {
                angle: data.angle.degree,
                distance: data.distance,
                force: data.force,
            }
            if (self.timer === -1) {
                self.#sendMove()
                self.timer = setInterval(() => self.#sendMove(), 250)
            }
        });

        this.joystick.on('end', function (evt, data) {
            if (self.timer !== -1) clearInterval(self.timer);

            self.timer = -1;
            self.vector = self.zero_vector;
            self.#sendMove();
        });
    }
}
