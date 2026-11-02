# Setup — Windows laptop with the RTX 2060 (the model server)

This machine does one job: serve a model on your local network, fast.
The MacBook holds the memory and runs the harness.

**Do not expose this to the internet.** Local Wi-Fi only, private firewall
profile only. There is no authentication on the Ollama port — anyone who can
reach it can use your GPU.

---

## What the 2060 can actually do

6 GB of VRAM. That is the whole constraint.

| Model | Size (Q4) | Fits? | Speed | Verdict |
|---|---|---|---|---|
| qwen2.5:3b | 2.0 GB | yes, easily | 40–60 tok/s | too small for the GPU |
| **qwen2.5:7b** | ~4.7 GB | yes, tight | 25–40 tok/s | **the sweet spot** |
| qwen2.5:14b | ~9 GB | partial offload | 5–8 tok/s | slow but usable for hard questions |
| qwen2.5-coder:7b | ~4.7 GB | yes | 25–35 tok/s | best for `debug` mode |

Start with `qwen2.5:7b`. If you do a lot of coding, add
`qwen2.5-coder:7b` and switch with `ATLAS_MODEL`.

Expect the laptop fan to spin. That's the GPU earning its keep.

---

## 1. Run the installer

Open PowerShell in the `atlas` folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

It will:

1. download portable Ollama into `.\vendor\ollama` (1.6 GB, no system install)
2. start it bound to `0.0.0.0:11434`
3. pull `qwen2.5:7b`
4. add a firewall rule for the **Private** profile only
5. print the address to paste into the MacBook's `.env`

You need internet for step 1 and 3, and Administrator for the firewall rule.

---

## 2. If you'd rather do it by hand

```powershell
# portable, self-contained
Invoke-WebRequest https://ollama.com/download/ollama-windows-amd64.zip -OutFile ollama.zip
Expand-Archive ollama.zip -DestinationPath vendor\ollama
$env:OLLAMA_HOST = "0.0.0.0:11434"
vendor\ollama\ollama.exe serve

# firewall (admin PowerShell)
New-NetFirewallRule -DisplayName "Atlas Ollama (LAN)" -Direction Inbound `
  -LocalPort 11434 -Protocol TCP -Action Allow -Profile Private

# model
vendor\ollama\ollama.exe pull qwen2.5:7b
```

Find your LAN IP:

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" }
```

---

## 3. Make it survive reboots

Ollama as a login task (no admin needed):

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\Users\YOU\dev\atlas\vendor\ollama\ollama.exe" `
           -Argument "serve" -WorkingDirectory "C:\Users\YOU\dev\atlas"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "Atlas Model Server" -Action $action -Trigger $trigger
```

Keep the machine from sleeping while plugged in:

```powershell
powercfg /change standby-timeout-ac 0
```

Lid closed = asleep = the Mac loses its model. Either keep the lid open or use
`powercfg` plus a "do nothing when lid closes" setting.

---

## 4. Static IP, so you don't edit `.env` weekly

Router admin → DHCP reservation for this machine's MAC address. Otherwise your
`ATLAS_BASE_URL` breaks every time the router reassigns.

---

## 5. Verify from the MacBook

```bash
curl http://<LAN-IP>:11434/api/version     # {"version":"0.40.x"}
curl http://<LAN-IP>:11434/api/tags        # should list qwen2.5:7b
```

Then `atlas check` on the Mac. If both pass, you're done: the Mac is the brain,
the 2060 is the muscle.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Mac gets `Connection refused` | server bound to 127.0.0.1 | `OLLAMA_HOST=0.0.0.0:11434`, restart |
| Times out | firewall blocking | check the Private-profile rule |
| Works, then stops | laptop slept | `powercfg`, keep lid open |
| Very slow | 7B spilling to CPU | check `ollama ps`; a 14B will do this |
| IP changed | DHCP | router reservation |
| Only works on the same subnet | Guest Wi-Fi isolating clients | use the main network |
