/*
 ImobHunter-BR — Motion System / After Effects
 ------------------------------------------------
 Direção:
 - Product-film premium / UI cinematográfica
 - câmera 3D fluida, profundidade real, parallax e micro-movimento
 - tipografia Inter, grade editorial, verde #35FF77 sobre #06111B
 - partículas discretas, sem aparência "tech genérica"
 - referência de linguagem: product films da Apple, spatial UI da Linear,
   mapas/câmera do Mapbox e motion editorial de interfaces SaaS premium.
 - Não copia nenhuma peça; usa apenas princípios de composição, ritmo e câmera.

 Composição: 1920x1080 / 30fps / 12s
 Render alvo: ProRes 422 HQ para master + H.264 para web
*/

(function () {
    app.beginUndoGroup("ImobHunter-BR Motion System");

    var W = 1920, H = 1080, FPS = 30, DUR = 12;
    var comp = app.project.items.addComp("IMOBHUNTER_MASTER_12S", W, H, 1, DUR, FPS);
    comp.bgColor = hex("#06111B");

    function hex(h) {
        h = h.replace("#", "");
        return [
            parseInt(h.substr(0,2),16)/255,
            parseInt(h.substr(2,2),16)/255,
            parseInt(h.substr(4,2),16)/255
        ];
    }

    var C = {
        bg: hex("#06111B"),
        panel: hex("#0A1827"),
        panel2: hex("#0E1C2B"),
        line: hex("#1D3449"),
        text: hex("#EDF5FA"),
        muted: hex("#91A5B6"),
        green: hex("#35FF77"),
        blue: hex("#68B8FF"),
        pink: hex("#FF7894")
    };

    function setColor(prop, color) { prop.setValue(color); }

    function textLayer(name, txt, size, color, x, y, z, weight) {
        var l = comp.layers.addText(txt);
        l.name = name;
        // Every text element participates in the real 3D camera scene.
        // This keeps z-depth, parallax and camera movement consistent with the UI panels.
        l.threeDLayer = true;
        var d = l.property("Source Text").value;
        d.font = "Inter";
        d.fontSize = size;
        d.fillColor = color;
        d.applyFill = true;
        d.strokeColor = [0,0,0];
        d.applyStroke = false;
        d.justification = ParagraphJustification.LEFT_JUSTIFY;
        if (weight) d.fontStyle = weight;
        l.property("Source Text").setValue(d);
        l.property("Position").setValue([x,y,z || 0]);
        return l;
    }

    function rect(name, w, h, color, x, y, z, radius) {
        var l = comp.layers.addShape();
        l.name = name;
        l.threeDLayer = true;
        var g = l.property("Contents").addProperty("ADBE Vector Group");
        var r = g.property("Contents").addProperty("ADBE Vector Shape - Rect");
        r.property("Size").setValue([w,h]);
        if (radius) r.property("Roundness").setValue(radius);
        var f = g.property("Contents").addProperty("ADBE Vector Graphic - Fill");
        f.property("Color").setValue(color);
        l.property("Transform").property("Position").setValue([x,y,z || 0]);
        return l;
    }

    function animateOpacity(layer, t0, t1, from, to) {
        var p = layer.property("Transform").property("Opacity");
        p.setValueAtTime(t0, from);
        p.setValueAtTime(t1, to);
    }

    function ease(prop) {
        for (var i = 1; i <= prop.numKeys; i++) {
            prop.setTemporalEaseAtKey(i, [new KeyframeEase(0,75)], [new KeyframeEase(0,75)]);
        }
    }

    // 01 — Atmosphere / cinematic base
    var bg = comp.layers.addSolid(C.bg, "BACKGROUND", W, H, 1);
    bg.threeDLayer = true;
    bg.property("Position").setValue([W/2,H/2,600]);

    var glow = comp.layers.addSolid(C.green, "GREEN_ATMOSPHERE", 900, 900, 1);
    glow.threeDLayer = true;
    glow.property("Opacity").setValue(7);
    glow.property("Position").setValue([1450,180,250]);
    var blur = glow.property("Effects").addProperty("ADBE Gaussian Blur 2");
    blur.property("Blurriness").setValue(160);

    // 02 — Editorial grid
    var grid = comp.layers.addShape();
    grid.name = "EDITORIAL_GRID";
    grid.threeDLayer = true;
    var contents = grid.property("Contents");
    for (var gx = 0; gx <= W; gx += 160) {
        var gv = contents.addProperty("ADBE Vector Shape - Group");
        var path = gv.property("Contents").addProperty("ADBE Vector Shape - Group");
        var line = new Shape();
        line.vertices = [[gx,0],[gx,H]];
        line.inTangents = [[0,0],[0,0]];
        line.outTangents = [[0,0],[0,0]];
        line.closed = false;
        path.property("Path").setValue(line);
        var stroke = gv.property("Contents").addProperty("ADBE Vector Graphic - Stroke");
        stroke.property("Color").setValue(C.line);
        stroke.property("Opacity").setValue(25);
        stroke.property("Stroke Width").setValue(1);
    }
    for (var gy = 0; gy <= H; gy += 120) {
        var gh = contents.addProperty("ADBE Vector Shape - Group");
        var path2 = gh.property("Contents").addProperty("ADBE Vector Shape - Group");
        var line2 = new Shape();
        line2.vertices = [[0,gy],[W,gy]];
        line2.inTangents = [[0,0],[0,0]];
        line2.outTangents = [[0,0],[0,0]];
        line2.closed = false;
        path2.property("Path").setValue(line2);
        var stroke2 = gh.property("Contents").addProperty("ADBE Vector Graphic - Stroke");
        stroke2.property("Color").setValue(C.line);
        stroke2.property("Opacity").setValue(18);
        stroke2.property("Stroke Width").setValue(1);
    }
    grid.property("Opacity").setValue(0);
    animateOpacity(grid, 0.0, 1.1, 0, 55);

    // 03 — Floating particles: sparse, slow, depth-based
    for (var i = 0; i < 42; i++) {
        var p = comp.layers.addShape();
        p.name = "PARTICLE_" + ("00" + i).slice(-2);
        p.threeDLayer = true;
        var pg = p.property("Contents").addProperty("ADBE Vector Group");
        var pr = pg.property("Contents").addProperty("ADBE Vector Shape - Ellipse");
        var s = 2 + (i % 3);
        pr.property("Size").setValue([s,s]);
        var pf = pg.property("Contents").addProperty("ADBE Vector Graphic - Fill");
        pf.property("Color").setValue(i % 5 === 0 ? C.green : C.muted);
        p.property("Opacity").setValue(18 + (i % 5) * 5);
        var px = 80 + ((i * 347) % 1760);
        var py = 70 + ((i * 193) % 940);
        var pz = -250 + ((i * 127) % 900);
        p.property("Position").setValueAtTime(0, [px,py,pz]);
        p.property("Position").setValueAtTime(DUR, [px + ((i%4)-2)*35, py + ((i%3)-1)*25, pz]);
    }

    // 04 — 3D camera: slow push-in + lateral parallax
    var cam = comp.layers.addCamera("CAMERA_CINEMATIC", [W/2,H/2]);
    cam.autoOrient = AutoOrientType.NO_AUTO_ORIENT;
    var camOpt = cam.property("Camera Options");
    camOpt.property("Depth of Field").setValue(true);
    camOpt.property("Focus Distance").setValue(1900);
    camOpt.property("Aperture").setValue(28);
    camOpt.property("Blur Level").setValue(18);
    cam.position.setValueAtTime(0, [960,540,1900]);
    cam.position.setValueAtTime(3.2, [1010,530,1450]);
    cam.position.setValueAtTime(7.0, [910,550,1250]);
    cam.position.setValueAtTime(12, [960,540,1550]);
    cam.pointOfInterest.setValueAtTime(0, [960,540,0]);
    cam.pointOfInterest.setValueAtTime(3.2, [980,535,0]);
    cam.pointOfInterest.setValueAtTime(7.0, [930,550,0]);
    cam.pointOfInterest.setValueAtTime(12, [960,540,0]);
    ease(cam.position);
    ease(cam.pointOfInterest);
    camOpt.property("Focus Distance").setValueAtTime(0, 1900);
    camOpt.property("Focus Distance").setValueAtTime(3.2, 1500);
    camOpt.property("Focus Distance").setValueAtTime(7.0, 1250);
    camOpt.property("Focus Distance").setValueAtTime(12, 1550);
    ease(camOpt.property("Focus Distance"));

    // 05 — Hero copy
    var eyebrow = textLayer("EYEBROW", "CAÇANDO OPORTUNIDADES  •  BRASIL", 24, C.green, 150, 210, 80, "Bold");
    var title = textLayer("TITLE", "Dados reais.\nDecisões inteligentes.", 92, C.text, 150, 335, 40, "Bold");
    var sub = textLayer("SUBTITLE", "Inteligência imobiliária local-first para quem transforma\ninformação territorial em oportunidade.", 30, C.muted, 150, 560, 50, "Regular");
    animateOpacity(eyebrow, 0, .45, 0, 100);
    animateOpacity(title, .25, 1.05, 0, 100);
    animateOpacity(sub, .55, 1.45, 0, 100);

    // 06 — Product window, deep 3D
    var window = rect("PRODUCT_WINDOW", 1040, 570, C.panel, 1320, 570, -80, 28);
    window.property("Opacity").setValue(0);
    window.property("Transform").property("Scale").setValueAtTime(.7,[88,88,88]);
    window.property("Transform").property("Scale").setValueAtTime(1.9,[100,100,100]);
    animateOpacity(window,.7,1.9,0,100);
    window.property("Transform").property("Orientation").setValueAtTime(.7,[0,-7,0]);
    window.property("Transform").property("Orientation").setValueAtTime(1.9,[0,0,0]);

    rect("WINDOW_BAR", 1040, 72, C.panel2, 1320, 320, -60, 18);
    var appName = textLayer("APP_NAME", "ImobHunter-BR  •  Pesquisa imobiliária", 22, C.text, 875, 330, -50, "Bold");
    var search = rect("SEARCH_FIELD", 900, 64, hex("#0C1A28"), 1320, 430, -45, 14);
    var searchText = textLayer("SEARCH_TEXT", "Endereço, número, quadra ou lote", 18, C.muted, 900, 437, -35, "Regular");
    var badge = rect("VISUAL_BADGE", 120, 42, C.green, 1710, 430, -30, 10);
    var badgeText = textLayer("VISUAL_BADGE_TEXT", "VISUAL", 15, hex("#04100A"), 1675, 435, -20, "Bold");

    // 07 — Intelligence cards
    var labels = ["FONTES","COBERTURA","PROCESSAMENTO","PROVENIÊNCIA"];
    var vals = ["15+","BR","LOCAL","100%"];
    var cols = [C.green,C.blue,C.pink,hex("#73E4A1")];
    for (var c = 0; c < 4; c++) {
        var cx = 900 + c*235;
        rect("CARD_"+c, 205, 125, C.panel2, cx, 555, -30, 14);
        textLayer("CARD_LABEL_"+c, labels[c], 13, C.muted, cx-85, 530, -20, "Bold");
        var v = textLayer("CARD_VALUE_"+c, vals[c], 38, cols[c], cx-85, 590, -20, "Bold");
        animateOpacity(v, 1.4+c*.08, 1.7+c*.08, 0, 100);
    }

    // 08 — Source constellation: data becomes a dossier
    var sourceTitle = textLayer("SOURCE_TITLE", "Uma fonte isolada é informação.\nVárias fontes reconciliadas viram inteligência.", 48, C.text, 150, 760, 20, "Bold");
    animateOpacity(sourceTitle, 4.2, 5.0, 0, 100);

    var chips = ["GeoSampa","IBGE/CNEFE","SINTER/CIB","SNCR","SICAR","SIGEF","CNIR","CNPJ","ICMBio","IPHAN","OSM","IPTU"];
    for (var k = 0; k < chips.length; k++) {
        var xx = 260 + (k%4)*230;
        var yy = 820 + Math.floor(k/4)*70;
        var chip = rect("SOURCE_"+k, 195, 44, k%4===0 ? hex("#102B1E") : C.panel2, xx, yy, 0, 22);
        var chipText = textLayer("SOURCE_TEXT_"+k, chips[k], 15, k%4===0 ? C.green : C.muted, xx-78, yy+6, 10, "Bold");
        animateOpacity(chip, 4.7+k*.06, 5.0+k*.06, 0, 100);
        animateOpacity(chipText, 4.8+k*.06, 5.1+k*.06, 0, 100);
    }

    // 09 — CTA end frame
    var endTitle = textLayer("END_TITLE", "Caçando oportunidades.", 82, C.text, 150, 300, 30, "Bold");
    var endSub = textLayer("END_SUB", "ImobHunter-BR", 34, C.green, 150, 395, 30, "Bold");
    animateOpacity(endTitle, 8.5, 9.2, 0, 100);
    animateOpacity(endSub, 8.9, 9.6, 0, 100);

    var cta = rect("CTA", 300, 70, C.green, 310, 520, 20, 16);
    var ctaText = textLayer("CTA_TEXT", "CONHECER A PLATAFORMA", 18, hex("#04100A"), 180, 528, 30, "Bold");
    animateOpacity(cta, 9.2, 9.7, 0, 100);
    animateOpacity(ctaText, 9.25, 9.75, 0, 100);

    // 10 — Subtle logo mark
    var logoMark = rect("LOGO_MARK", 88, 88, C.panel2, 1740, 900, 30, 22);
    var mark = textLayer("LOGO_MARK_TEXT", "IH", 26, C.green, 1715, 910, 40, "Bold");
    animateOpacity(logoMark, 8.8, 9.4, 0, 100);
    animateOpacity(mark, 8.9, 9.5, 0, 100);

    // Motion language: no bounce, no elastic overshoot.
    // Use long ease curves and controlled depth. Premium = restraint.
    // The camera, typography and UI are all true 3D layers; z values are intentional.
    comp.workAreaStart = 0;
    comp.workAreaDuration = DUR;

    // Master render notes stored as markers.
    var markers = [
        [0.0,"OPEN — grid + particles + camera push"],
        [0.7,"HERO — typography enters"],
        [1.9,"PRODUCT — 3D UI reveal"],
        [4.2,"INTELLIGENCE — source constellation"],
        [8.5,"PAYOFF — brand statement"],
        [9.2,"CTA — platform"],
        [12.0,"OUTRO"]
    ];
    for (var m=0;m<markers.length;m++) {
        comp.markerProperty.setValueAtTime(markers[m][0], new MarkerValue(markers[m][1]));
    }

    app.endUndoGroup();
    alert("ImobHunter-BR Motion System criado: IMOBHUNTER_MASTER_12S");
})();