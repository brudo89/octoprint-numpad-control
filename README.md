# octoprint-numpad-control
Control 3d printer connected to OctoPrint using numerical Keyboard connected to host

<b>Warning: All connected keyboards will trigger api requests</b>

<h2>How to install:</h2>
1. Clone repository

2. Create virtualenv, activate and install requirements<br>
    <code>python3 -m venv venv</code><br>
    <code>source venv/bin/activate</code><br>
    <code>pip install -r requirements.txt</code>

2. Adjust SCN-codes and settings in <code>numcfg.py</code> to your keyboard and 3D Printer.<br>
<code>numctl.py</code> will read api key from <code>~/.octoprint/config.yaml</code> if not set in <code>numctl.py</code>.

3. Adjust <code>WorkingDirectory</code> in <code>numctl.service</code> to repo path and install<br>
    <code>sudo cp numctl.service /etc/systemd/system/numctl.service</code><br>
    <code>sudo systemctl start numctl.service</code><br>
    <code>sudo systemctl enable numctl.service</code>
    
4. Test keyboard controls and check log<br>
    <code>journalctl -u numctl.service -f</code>
