# Troubleshooting Guide

Common issues and solutions for hisense2mqtt.

## Connection Issues

### TV Not Responding

**Symptoms:**
- "Failed to connect to TV" in logs
- Availability shows "offline"
- Commands have no effect

**Solutions:**

1. **Verify TV IP address**
   ```bash
   ping 10.0.0.194
   ```
   If no response, check:
   - TV is powered on
   - TV is connected to network
   - IP address is correct

2. **Check TV port is open**
   ```bash
   nc -zv 10.0.0.194 36669
   ```
   If connection refused:
   - Try restarting the TV
   - Check TV network settings

3. **Verify UUID is paired**
   The UUID must be from a device that was paired with the TV via the Vidaa app. Try:
   - Re-pairing with the Vidaa app
   - Using a different UUID

4. **Check certificates**
   Ensure the `certs/` directory contains valid certificate files:
   ```bash
   ls -la certs/
   ```

### MQTT Broker Connection Failed

**Symptoms:**
- "Failed to connect to MQTT broker" in logs
- No topics published

**Solutions:**

1. **Verify broker is running**
   ```bash
   mosquitto_sub -h 192.168.1.100 -t "test" -v
   ```

2. **Check credentials**
   ```yaml
   mqtt:
     username: "correct_user"
     password: "correct_pass"
   ```

3. **Check network access**
   ```bash
   nc -zv 192.168.1.100 1883
   ```

4. **Review broker logs**
   For Mosquitto:
   ```bash
   tail -f /var/log/mosquitto/mosquitto.log
   ```

### TV Rejects the Connection (CONNACK code 5)

**Symptoms:**
```
Connection to 192.168.1.50:36669 failed with code 5 (not authorized ...)
```

Code 5 arrives *after* the TLS handshake completes, so the client certificates
are fine - the TV is rejecting the username/password/client_id.

**Solutions:**

1. **Old firmware needs static credentials.** Check the reported protocol:
   ```bash
   tv discover --method probe --verbose      # look for transport_protocol
   ```
   Anything below 3000 (e.g. `1140`) predates the dynamic credential algorithm.
   `auto` mode now tries static first for those, but you can force it:
   ```bash
   tv --ip 192.168.1.50 --auth-mode static status
   tv config add 192.168.1.50 --auth-mode static    # persist it
   ```
   These TVs issue no token - they authorize the client_id after the PIN - so
   the pairing is stored without one.

2. **Check the TV clock.** Dynamic credentials are time-based, so a wrong
   date/time, timezone, or DST setting on the TV gets them rejected.

3. **Clear a stale saved token**, e.g. after a TV factory reset or a pairing
   reset:
   ```bash
   tv auth clear
   tv auth pair
   ```

4. **Confirm the MAC is right.** Dynamic credentials hash the TV's MAC; the TV
   recomputes it from its own. `tv config show` should list a real MAC, not the
   IP placeholder.

## Wake-on-LAN Issues

### TV Won't Turn On

**Symptoms:**
- `set/power ON` command sent
- TV stays off
- No errors in logs

**Solutions:**

1. **Enable WoL on TV**
   - Settings > System > Power > Wake on LAN: ON
   - Or: Settings > Network > Network Standby: ON

2. **Use Ethernet connection**
   WiFi Wake-on-LAN is unreliable. Connect TV via Ethernet.

3. **Verify MAC address**
   ```bash
   # Check configured MAC
   grep mac config.yaml

   # Verify with arp
   arp -a | grep 10.0.0.194
   ```

4. **Test WoL directly**
   ```bash
   # Install wakeonlan tool
   sudo apt install wakeonlan

   # Send magic packet
   wakeonlan 84:C8:A0:C0:CE:8F
   ```

5. **Check broadcast packets**
   Container must use `network_mode: host` for WoL broadcasts.

## Home Assistant Discovery Issues

### Entity Not Appearing

**Symptoms:**
- No TV entity in Home Assistant
- Discovery topics not published

**Solutions:**

1. **Verify MQTT integration**
   - Settings > Devices & Services > MQTT
   - Check status shows "Connected"

2. **Check discovery prefix**
   ```yaml
   mqtt:
     discovery_prefix: "homeassistant"  # Must match HA config
   ```

3. **View discovery messages**
   ```bash
   mosquitto_sub -h localhost -t "homeassistant/#" -v
   ```

4. **Restart Home Assistant**
   Sometimes required after first discovery.

5. **Check `options.discovery: true`**
   Discovery must be enabled in config.

### Entity Shows Unavailable

**Symptoms:**
- Entity appears but shows "Unavailable"
- Orange warning icon

**Solutions:**

1. **Check availability topic**
   ```bash
   mosquitto_sub -h localhost -t "hisense2mqtt/+/state/available"
   ```
   Should show `online`

2. **Verify hisense2mqtt is running**
   ```bash
   docker compose ps
   docker compose logs hisense2mqtt
   ```

3. **Restart the bridge**
   ```bash
   docker compose restart
   ```

## Command Issues

### Power Toggle Not Working

**Symptoms:**
- Commands are sent (visible in logs)
- TV doesn't respond

**Solutions:**

1. **Check UUID is authorized**
   Only UUIDs paired via Vidaa app work. Try:
   ```bash
   # Test with CLI tool
   python3 -m pyvidaa.cli power
   ```

2. **Verify MQTT messages**
   ```bash
   mosquitto_sub -h localhost -t "hisense2mqtt/+/set/#" -v
   ```

3. **Check debug logs**
   Set `LOG_LEVEL: DEBUG` in config.

### Volume Not Updating

**Symptoms:**
- Volume commands work
- State doesn't update

**Solutions:**

1. **Increase poll interval**
   Default is 30 seconds. Volume is polled, not pushed.

2. **Check poll thread**
   Look for "Poll error" in logs.

## Docker Issues

### Container Won't Start

**Symptoms:**
- Container exits immediately
- "Exited (1)" status

**Solutions:**

1. **Check logs**
   ```bash
   docker compose logs hisense2mqtt
   ```

2. **Validate config**
   ```bash
   docker compose run --rm hisense2mqtt python -m hisense2mqtt --validate
   ```

3. **Check file permissions**
   ```bash
   ls -la config.yaml certs/
   ```

### Network Mode Host Not Working

**Symptoms:**
- WoL not working
- Can't reach broker

**Solutions:**

On some systems, `network_mode: host` doesn't work properly:

1. **Try bridge network with port mapping**
   ```yaml
   services:
     hisense2mqtt:
       network_mode: bridge
       # Note: WoL won't work in bridge mode
   ```

2. **Use macvlan network**
   For proper network isolation with broadcast support.

## Debug Mode

Enable verbose logging:

```yaml
options:
  log_level: "DEBUG"
```

Or via environment:
```bash
docker compose run -e LOG_LEVEL=DEBUG hisense2mqtt
```

## Getting Help

If you're still stuck:

1. **Collect logs**
   ```bash
   docker compose logs hisense2mqtt > hisense2mqtt.log
   ```

2. **Check config** (remove passwords)
   ```bash
   cat config.yaml | grep -v password
   ```

3. **Test MQTT**
   ```bash
   mosquitto_pub -h broker -t "test" -m "hello"
   mosquitto_sub -h broker -t "test"
   ```

4. **Test TV directly**
   ```bash
   python3 -m pyvidaa.cli --ip 10.0.0.194 power
   ```

## FAQ

**Q: Can I control multiple TVs?**
A: Yes, run multiple instances with different configs.

**Q: Does this work with all Hisense TVs?**
A: Works with Vidaa-based Hisense TVs. Some older models may not be compatible.

**Q: Why do I need the Vidaa app first?**
A: The app pairs a UUID with the TV. Only paired UUIDs are authorized.

**Q: Can I use this without Home Assistant?**
A: Yes, any MQTT client can publish commands and subscribe to state.

**Q: How do I find my TV's MAC address?**
A: TV Settings > Network > Network Status, or check your router's device list.
