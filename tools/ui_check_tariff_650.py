from playwright.sync_api import sync_playwright
U="https://127.0.0.1:18797/"
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome")
    pg=b.new_page(ignore_https_errors=True, viewport={"width":390,"height":1000})
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(U); pg.request.post(U+"api/auth/login", data={"username":"admin","password":"pw12345678"})
    pg.goto(U); pg.wait_for_timeout(2500)
    pg.evaluate("()=>{const a=Alpine.store('app'); a.showDisclaimer=false; a.activeTab='energy_costs'}")
    pg.wait_for_timeout(1500)
    pg.get_by_role("button", name="Plans & meters").first.click(); pg.wait_for_timeout(1500)
    print("meters:", [m["name"] for m in pg.request.get(U+"api/meters").json().get("meters", [])])
    def add(cancel):
        pg.get_by_role("button", name="+ Add tariff").first.click(); pg.wait_for_timeout(600)
        pg.click("[data-testid=tariff-new-retailer]"); pg.wait_for_timeout(300)
        pg.get_by_placeholder("AGL", exact=True).fill("Test Retailer"); pg.get_by_placeholder("Ausgrid").fill("Ausgrid")
        pg.get_by_role("button", name="Save", exact=True).first.click(); pg.wait_for_timeout(400)
        print("  select shows:", pg.locator("[data-testid=tariff-retailer] option:checked").inner_text())
        print("  retailers before tariff save:", [u["name"] for u in pg.request.get(U+"api/utilities").json()["utilities"]])
        pg.get_by_placeholder("AGL Home").fill("Plan A")
        pg.get_by_role("button", name="Energy rates").click(); pg.get_by_role("button", name="Dynamic (live)").click()
        if cancel:
            pg.get_by_role("button", name="Cancel", exact=True).last.click()
        else:
            pg.get_by_role("button", name="Save", exact=True).last.click()
        pg.wait_for_timeout(1200)
        print("  after", "Cancel" if cancel else "Save", "retailers:", [u["name"] for u in pg.request.get(U+"api/utilities").json()["utilities"]],
              "tariffs:", [(t["name"], t.get("meter_id") is not None) for t in pg.request.get(U+"api/tariffs").json()["tariffs"]])
    add(True); add(False)
    pg.locator("[data-testid=meter-plan]").first.get_by_role("button", name="Edit", exact=True).click(); pg.wait_for_timeout(800)
    pg.get_by_role("button", name="Energy rates").click(); pg.wait_for_timeout(400)
    pg.get_by_role("button", name="Cancel", exact=True).last.click(); pg.wait_for_timeout(800)
    print("edited dynamic tariff, then Cancel")
    print("page errors:", errs or "none")
    b.close()
