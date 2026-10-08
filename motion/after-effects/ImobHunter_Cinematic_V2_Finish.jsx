/*
 ImobHunter-BR — CINEMATIC V2 / FINISH PASS
 --------------------------------------------
 Executar DEPOIS de:
   ImobHunter_Cinematic_V2_16s.jsx

 Este script não recria a peça.
 Ele faz o acabamento cinematográfico da composição ativa:
 - motion blur real;
 - shutter controlado;
 - profundidade de campo da câmera;
 - ajustes sutis de blur em atmosfera;
 - organização visual;
 - markers de acabamento.

 Não altera a landing e não depende de plugins externos.
*/

(function () {
    app.beginUndoGroup("ImobHunter-BR Cinematic V2 Finish");

    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) {
        alert("Abra/seleccione a composição IMOBHUNTER_CINEMATIC_V2_16S antes de executar o Finish Pass.");
        app.endUndoGroup();
        return;
    }

    function safeProperty(layer, groupName, propName) {
        try {
            var g = layer.property(groupName);
            if (!g) return null;
            return g.property(propName);
        } catch(e) {
            return null;
        }
    }

    function setIf(p, value) {
        try {
            if (p) p.setValue(value);
        } catch(e) {}
    }

    function addBlur(layer, amount) {
        try {
            var fx = layer.property("Effects").addProperty("ADBE Gaussian Blur 2");
            fx.property("Blurriness").setValue(amount);
            fx.property("Repeat Edge Pixels").setValue(true);
            return fx;
        } catch(e) {
            return null;
        }
    }

    // ------------------------------------------------------------
    // 01 — Global cinematic shutter
    // ------------------------------------------------------------
    try {
        comp.motionBlur = true;
        comp.shutterAngle = 180;
        comp.shutterPhase = -90;
    } catch(e) {}

    // ------------------------------------------------------------
    // 02 — Layer motion blur
    // ------------------------------------------------------------
    for (var i=1; i<=comp.numLayers; i++) {
        var layer = comp.layer(i);

        try {
            if (layer.threeDLayer && layer.name.indexOf("PARTICLE_") === 0) {
                layer.motionBlur = true;
            } else if (layer.threeDLayer && layer.name.indexOf("GRID_") !== 0) {
                layer.motionBlur = true;
            }
        } catch(e) {}
    }

    // ------------------------------------------------------------
    // 03 — Camera depth of field
    // ------------------------------------------------------------
    var camera = null;
    for (var c=1; c<=comp.numLayers; c++) {
        if (comp.layer(c).name === "CAMERA_3D_CINEMATIC") {
            camera = comp.layer(c);
            break;
        }
    }

    if (camera) {
        try {
            var opts = camera.property("ADBE Camera Options Group");
            if (opts) {
                var dof = opts.property("ADBE Camera Depth of Field");
                var focus = opts.property("ADBE Camera Focus Distance");
                var aperture = opts.property("ADBE Camera Aperture");
                var blurLevel = opts.property("ADBE Camera Blur Level");

                setIf(dof, true);
                setIf(aperture, 120);
                setIf(blurLevel, 70);

                if (focus) {
                    focus.setValueAtTime(0, 1850);
                    focus.setValueAtTime(2.7, 1420);
                    focus.setValueAtTime(6.0, 1050);
                    focus.setValueAtTime(9.0, 1200);
                    focus.setValueAtTime(12.4, 1350);
                    focus.setValueAtTime(16.0, 1650);
                }
            }
        } catch(e) {}
    }

    // ------------------------------------------------------------
    // 04 — Atmospheric restraint
    // ------------------------------------------------------------
    var glowNames = ["01_GREEN_GLOW","02_BLUE_GLOW"];
    for (var g=0; g<glowNames.length; g++) {
        for (var j=1; j<=comp.numLayers; j++) {
            if (comp.layer(j).name === glowNames[g]) {
                // Keep atmosphere soft: never let the glow become a UI effect.
                var op = safeProperty(comp.layer(j),"ADBE Transform Group","ADBE Opacity");
                if (op) {
                    var current = op.value;
                    op.setValue(Math.min(current, g === 0 ? 5 : 3));
                }
                addBlur(comp.layer(j), g === 0 ? 180 : 210);
            }
        }
    }

    // ------------------------------------------------------------
    // 05 — Premium timing markers
    // ------------------------------------------------------------
    var finishMarkers = [
        [0.00,"FINISH — 180° shutter / restrained motion blur"],
        [1.75,"FINISH — UI depth begins"],
        [4.05,"FINISH — evidence transition"],
        [6.20,"FINISH — dossier focus"],
        [10.00,"FINISH — visual simplification"],
        [14.90,"FINISH — final fade"]
    ];

    for (var m=0; m<finishMarkers.length; m++) {
        try {
            comp.markerProperty.setValueAtTime(
                finishMarkers[m][0],
                new MarkerValue(finishMarkers[m][1])
            );
        } catch(e) {}
    }

    app.endUndoGroup();

    alert(
        "ImobHunter-BR Finish Pass aplicado.\n\n" +
        "Motion blur: 180°\n" +
        "DOF: ativo\n" +
        "Atmosfera: controlada\n" +
        "Markers: adicionados"
    );
})();
