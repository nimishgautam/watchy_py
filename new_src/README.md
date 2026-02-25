New firmware I'm making based on old stuff

## flashing
see scripts directory (note my version connects on ttyACM0)

## How to run in rshell
connect serial /dev/ttyACM0
rsync -m new_src/src/ /pyboard/
repl ~ import reset ~