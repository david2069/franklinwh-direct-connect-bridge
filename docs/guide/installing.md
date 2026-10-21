# Installing, in pictures

[Back to the guide index](index.md)

A picture for each step of the three ways to install the bridge. The full text, including
prerequisites, upgrading and troubleshooting, is
[INSTALL.md](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/INSTALL.md).
Where this page and INSTALL.md disagree, INSTALL.md is the reference.

!!! tip "Back up Home Assistant first"
    Before installing the bridge, or any major update, take a Home Assistant backup:
    **Settings → System → Backups → Back up now**. Keeping copies off the premises is
    covered in [Your phone, notifications and access from away](phone-and-remote-access.md#backups-off-the-premises).

Every screenshot here was taken on 2026-10-16 with release 0.5.0 and **mock gateways
only**: no aGate, no MQTT broker, no cloud account. Each install started from scratch.

---

## Home Assistant add-on

Taken on Home Assistant OS 18.3 (generic-aarch64) in a virtual machine. Home Assistant
2026.10 calls add-ons **Apps**, so the menus read *Apps* and *App store* where INSTALL.md
says *Add-ons* and *Add-on Store*. Full text:
[INSTALL.md → Home Assistant add-on](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/INSTALL.md#1-home-assistant-add-on).

1. Start from a Home Assistant OS install that has finished booting.

    ![The Home Assistant OS console, ready](../images/installing/01-haos-console-ready.png)

2. Finish Home Assistant's own onboarding.

    ![Home Assistant's onboarding welcome page](../images/installing/02-ha-onboarding.png)

    ![Home Assistant after onboarding](../images/installing/03-ha-onboarding-done.png)

3. Open **Settings → Apps**.

    ![Home Assistant Settings](../images/installing/04-ha-settings.png)

    ![Settings → Apps, with nothing installed yet](../images/installing/05-ha-apps.png)

4. In the **App store**, open **⋮ → Repositories**.

    ![The App store's menu: Check for updates, Repositories, Registry credentials](../images/installing/06-ha-app-store-menu.png)

5. Select **+ Add**, enter `https://github.com/david2069/franklinwh-direct-connect-bridge`
   and select **Add**.

    ![The Repositories page, empty](../images/installing/07-ha-repositories.png)

    ![The Add repository dialog with the bridge's URL](../images/installing/08-ha-add-repository.png)

    ![The repository added](../images/installing/09-ha-repository-added.png)

6. Back in the App store, find **FranklinWH Direct Connect Bridge**.

    ![The App store searched for FranklinWH](../images/installing/10-ha-store-bridge.png)

7. Open it and select **Install**.

    ![The bridge's app page before installing](../images/installing/11-ha-app-page.png)

    ![The bridge installed and stopped](../images/installing/12-ha-installed.png)

8. **Configuration**: with a real aGate, set `fwh_host` to its IP address. These screenshots
   use a mock gateway, so `fwh_host` was left empty and nothing else was changed.

    ![The add-on's Configuration tab with its defaults](../images/installing/13-ha-configuration.png)

9. **Start**, then **Open Web UI**.

    ![The bridge running, with Open Web UI](../images/installing/14-ha-started.png)

10. Read the disclaimer, tick it, and continue.

    ![The unofficial-software disclaimer](../images/installing/15-ha-disclaimer.png)

11. The setup wizard opens. These screenshots take **Explore with a mock gateway**.

    ![Wizard: what would you like to do?](../images/installing/16-ha-wizard-intent.png)

12. **How much hardware**: one aGate and one aPower here.

    ![Wizard: how much hardware is installed](../images/installing/17-ha-wizard-hardware.png)

13. **Where is this site**: the timezone schedules run on.

    ![Wizard: the site's timezone](../images/installing/18-ha-wizard-timezone.png)

14. **Create mock gateway**.

    ![Wizard: create a mock gateway](../images/installing/19-ha-wizard-mock.png)

15. **FranklinWH app account**: optional. **Skip for now**.

    ![Wizard: the optional FranklinWH account](../images/installing/20-ha-wizard-cloud.png)

16. **Confirm** what the gateway reports.

    ![Wizard: what each gateway reports](../images/installing/21-ha-wizard-confirm.png)

17. **Publish to Home Assistant?** **No** here, because no MQTT broker is installed. It can be
    turned on later from the MQTT tab. Then **Finish**.

    ![Wizard: publishing left off](../images/installing/22-ha-wizard-publish-no.png)

    ![Wizard: ready](../images/installing/23-ha-wizard-done.png)

18. The Dashboard, with the mock gateway live.

    ![The Dashboard inside Home Assistant, with the mock live](../images/installing/24-ha-dashboard-mock.png)

---

## Docker

Taken on Debian 12 (arm64) with Docker Engine from Docker's own apt repository. Full text:
[INSTALL.md → Docker](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/INSTALL.md#2-docker-standalone).

1. Clone the repository and change into it.

    ![git clone of the repository](../images/installing/30-docker-clone.png)

2. Build the image with `docker build -t franklinwh-direct-connect-bridge:dev .`

    ![docker build, start and end of the output](../images/installing/31-docker-build.png)

3. Start it with `FWH_HOST=<your aGate IP> docker compose up -d`. Here the address is
   `192.0.2.10`, a documentation address that stands in for a real aGate.

    ![docker compose up -d, and docker compose ps showing the container healthy](../images/installing/32-docker-compose-up.png)

    !!! note "Exploring with a mock instead of an aGate"
        With `FWH_HOST` set, the bridge registers that address as a real gateway, so the
        setup wizard does not open on its own. `docker-compose.yml` also falls back to
        `192.0.2.110` when `FWH_HOST` is empty. INSTALL.md does not yet describe a no-hardware
        Docker run. To take the rest of these screenshots, the container was recreated
        with a fresh `./data` and a `docker-compose.override.yml` that sets `FWH_HOST=`
        (empty) and `MQTT_ENABLED=false`.

    ![The override file and the container recreated](../images/installing/33-docker-override.png)

4. Open `http://<host>:8101`. The disclaimer comes first.

    ![First open: the disclaimer](../images/installing/34-docker-first-open.png)

5. The setup wizard: **Explore with a mock gateway**, and the same steps as in the add-on
   section above.

    ![Wizard: what would you like to do?](../images/installing/35-docker-wizard-intent.png)

    ![Wizard: create a mock gateway](../images/installing/36-docker-wizard-mock.png)

    ![Wizard: what the mock gateway reports](../images/installing/37-docker-wizard-confirm.png)

    ![Wizard: publishing left off](../images/installing/38-docker-wizard-publish-no.png)

6. The Dashboard, with the mock gateway live.

    ![The Dashboard in Docker, with the mock live](../images/installing/39-docker-dashboard-mock.png)

---

## Standalone

Python in a virtual environment, on the same Debian 12 machine, from a fresh clone. Full
text:
[INSTALL.md → Without Docker](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/INSTALL.md#without-docker).

1. Create a virtual environment and install with `pip install ".[cloud]"`.

    ![python3 -m venv and pip install](../images/installing/50-standalone-venv-install.png)

2. Run `franklinwh-direct-connect-bridge run`.

    !!! warning "Release 0.5.0: the documented commands do not start the web UI"
        On 0.5.0 this step stops with `PermissionError: [Errno 13] Permission denied: '/data'`,
        because the metrics database path defaults to `/data/metrics.db` outside a
        container too. With that worked around, a non-editable `pip install ".[cloud]"`
        leaves out the web UI's templates and scripts, and the page answers
        `Internal Server Error`. Until this is fixed, the screenshots below used the
        editable install from INSTALL.md's *Development* section,
        `pip install -e ".[cloud]"`, and `METRICS_DB=./data/metrics.db`.

    ![The run failing with PermissionError on /data](../images/installing/51-standalone-run-fails.png)

    ![The editable install and a successful run](../images/installing/52-standalone-editable-run.png)

3. Open `http://<host>:8101`. The disclaimer comes first.

    ![First open: the disclaimer](../images/installing/53-standalone-first-open.png)

4. The setup wizard: **Explore with a mock gateway**, as above.

    ![Wizard: what would you like to do?](../images/installing/54-standalone-wizard-intent.png)

    ![Wizard: create a mock gateway](../images/installing/55-standalone-wizard-mock.png)

5. The Dashboard, with the mock gateway live.

    ![The standalone Dashboard, with the mock live](../images/installing/56-standalone-dashboard-mock.png)
