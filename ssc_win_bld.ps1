# powershell script to create a pyinstaller bundle

$revision = $args[0]
if ($null -eq $revision ) {
    $revision = read-host -Prompt "Please enter a revision number (Use the latest pull request number that you build from)"
}

rm seestar_alp_$revision.zip -ErrorAction SilentlyContinue
rmdir build -recurse -ErrorAction SilentlyContinue
rmdir dist -recurse -ErrorAction SilentlyContinue

pip install -r requirements.txt
pyinstaller --name="seestar_alp" `
--add-data="device/config.toml.example;." --add-data="front/citation;astroquery" --add-data="front/templates;front/templates" --add-data="front/public;front/public" `
--paths=./front --paths=./device `
root_app.py
Start-Sleep 5   # sleep was required for rename to work, go figure
cd dist/seestar_alp
#Compress-Archive -Path ./seestar_alp -DestinationPath ../win_seestar_alp_$revision.zip
#cd ../..
# clean up
#rm seestar_alp.spec
#rmdir build -recurse
#rmdir dist -recurse
