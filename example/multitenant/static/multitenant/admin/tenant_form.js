(function () {
  function setVisible(selector, visible) {
    document.querySelectorAll(selector).forEach((element) => {
      element.style.display = visible ? "" : "none";
      element.querySelectorAll("input, select, textarea").forEach((field) => {
        field.disabled = !visible;
      });
    });
  }

  function updateSections() {
    const isolation = document.getElementById("id_isolation_mode");
    const provisioning = document.getElementById("id_provisioning_mode");
    const isolationMode = isolation ? isolation.value : "";
    const provisioningMode = provisioning ? provisioning.value : "";

    const isSchema = isolationMode === "schema";
    const isDatabase = isolationMode === "database";
    const isManual = provisioningMode === "manual";

    setVisible("fieldset.tenant-section-schema-manual", isSchema && isManual);
    setVisible("fieldset.tenant-section-database-manual", isDatabase && isManual);
    setVisible("fieldset.tenant-section-database", isDatabase);
  }

  document.addEventListener("DOMContentLoaded", function () {
    const isolation = document.getElementById("id_isolation_mode");
    const provisioning = document.getElementById("id_provisioning_mode");

    if (isolation) {
      isolation.addEventListener("change", updateSections);
    }
    if (provisioning) {
      provisioning.addEventListener("change", updateSections);
    }

    updateSections();
  });
})();
