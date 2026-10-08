/*
 ImobHunter-BR — CINEMATIC MOTION V2 / After Effects
 ------------------------------------------------------
 1920x1080 • 30fps • 16s

 Objetivo:
 - transformar a identidade web existente em um product film contemporâneo;
 - câmera 3D fluida, parallax real, profundidade e movimentos motivados pelo conteúdo;
 - tipografia editorial, UI material, grade, partículas e luz controladas;
 - premium sem bounce/elastic exagerado;
 - referências de PRINCÍPIOS: Apple product film, Linear, Mapbox, Stripe,
   motion editorial contemporâneo. Não replica peças ou layouts.

 IMPORTANTE:
 - a landing permanece institucional;
 - este arquivo cria a peça cinematográfica no After Effects;
 - refinamento final de blur/DOF/color/curvas pode ser feito no AE.
*/

(function () {
    app.beginUndoGroup("ImobHunter-BR Cinematic Motion V2");

    var W = 1920, H = 1080, FPS = 30, DUR = 16;
    var comp = app.project.items.addComp("IMOBHUNTER_CINEMATIC_V2_16S", W, H, 1, DUR, FPS);
    comp.bgColor = [0.024,0.067,0.106];

    function hex(h) {
        h = h.replace("#","");
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
        pink: hex("#FF7894"),
        black: hex("#04100A")
    };

    function prop(layer, group, name) {
        return layer.property(group).property(name);
    }

    function easeProperty(p, influence) {
        if (!p || p.numKeys < 2) return;
        var inf = influence || 78;
        for (var i=1; i<=p.numKeys; i++) {
            try {
                p.setTemporalEaseAtKey(i, [new KeyframeEase(0,inf)], [new KeyframeEase(0,inf)]);
            } catch(e) {}
        }
    }

    function opacityIn(layer, t0, t1) {
        var p = prop(layer,"ADBE Transform Group","ADBE Opacity");
        p.setValueAtTime(t0,0);
        p.setValueAtTime(t1,100);
        easeProperty(p,82);
    }

    function scaleIn(layer, t0, t1, from) {
        var p = prop(layer,"ADBE Transform Group","ADBE Scale");
        var z = layer.threeDLayer ? [from,from,from] : [from,from];
        var one = layer.threeDLayer ? [100,100,100] : [100,100];
        p.setValueAtTime(t0,z);
        p.setValueAtTime(t1,one);
        easeProperty(p,84);
    }

    function move(layer, t0, t1, a, b) {
        var p = prop(layer,"ADBE Transform Group","ADBE Position");
        p.setValueAtTime(t0,a);
        p.setValueAtTime(t1,b);
        easeProperty(p,82);
    }

    function textLayer(name, txt, size, color, x, y, z, style) {
        var l = comp.layers.addText(txt);
        l.name = name;
        l.threeDLayer = true;
        var d = l.property("Source Text").value;
        d.font = "Inter";
        d.fontSize = size;
        d.fillColor = color;
        d.applyFill = true;
        d.applyStroke = false;
        d.justification = ParagraphJustification.LEFT_JUSTIFY;
        try { d.fontStyle = style || "Regular"; } catch(e) {}
        l.property("Source Text").setValue(d);
        l.property("Position").setValue([x,y,z || 0]);
        return l;
    }

    function roundedRect(name,w,h,color,x,y,z,r) {
        var l = comp.layers.addShape();
        l.name = name;
        l.threeDLayer = true;
        var root = l.property("Contents");
        var group = root.addProperty("ADBE Vector Group");
        var contents = group.property("Contents");
        var rect = contents.addProperty("ADBE Vector Shape - Rect");
        rect.property("Size").setValue([w,h]);
        rect.property("Roundness").setValue(r || 16);
        var fill = contents.addProperty("ADBE Vector Graphic - Fill");
        fill.property("Color").setValue(color);
        l.property("Transform").property("Position").setValue([x,y,z || 0]);
        return l;
    }

    function lineLayer(name,x1,y1,x2,y2,color,width,opacity,z) {
        var l = comp.layers.addShape();
        l.name = name;
        l.threeDLayer = true;
        var g = l.property("Contents").addProperty("ADBE Vector Group");
        var p = g.property("Contents").addProperty("ADBE Vector Shape - Group");
        var s = new Shape();
        s.vertices=[[x1,y1],[x2,y2]];
        s.inTangents=[[0,0],[0,0]];
        s.outTangents=[[0,0],[0,0]];
        s.closed=false;
        p.property("Path").setValue(s);
        var stroke = g.property("Contents").addProperty("ADBE Vector Graphic - Stroke");
        stroke.property("Color").setValue(color);
        stroke.property("Stroke Width").setValue(width || 1);
        stroke.property("Opacity").setValue(opacity || 20);
        l.property("Position").setValue([0,0,z || 0]);
        return l;
    }

    // ------------------------------------------------------------
    // 01 — cinematic atmosphere
    // ------------------------------------------------------------
    var bg = comp.layers.addSolid(C.bg,"00_BACKGROUND",W,H,1);
    bg.threeDLayer=true;
    bg.property("Position").setValue([W/2,H/2,900]);

    var greenGlow = comp.layers.addSolid(C.green,"01_GREEN_GLOW",900,900,1);
    greenGlow.threeDLayer=true;
    greenGlow.property("Position").setValue([1450,220,250]);
    greenGlow.property("Opacity").setValue(5);
    var gb=greenGlow.property("Effects").addProperty("ADBE Gaussian Blur 2");
    gb.property("Blurriness").setValue(180);
    move(greenGlow,0,DUR,[1450,220,250],[1320,360,450]);

    var blueGlow = comp.layers.addSolid(C.blue,"02_BLUE_GLOW",700,700,1);
    blueGlow.threeDLayer=true;
    blueGlow.property("Position").setValue([360,820,500]);
    blueGlow.property("Opacity").setValue(3);
    var bb=blueGlow.property("Effects").addProperty("ADBE Gaussian Blur 2");
    bb.property("Blurriness").setValue(210);
    move(blueGlow,0,DUR,[360,820,500],[520,700,650]);

    // ------------------------------------------------------------
    // 02 — editorial grid with depth drift
    // ------------------------------------------------------------
    var gridOpacity=42;
    for (var gx=0; gx<=W; gx+=160) {
        var gl=lineLayer("GRID_V_"+gx,gx,0,gx,H,C.line,1,gridOpacity,-120);
        gl.property("Opacity").setValueAtTime(0,0);
        gl.property("Opacity").setValueAtTime(1.15,gridOpacity);
        easeProperty(gl.property("Opacity"),86);
    }
    for (var gy=0; gy<=H; gy+=120) {
        var gh=lineLayer("GRID_H_"+gy,0,gy,W,gy,C.line,1,18,-120);
        gh.property("Opacity").setValueAtTime(0,0);
        gh.property("Opacity").setValueAtTime(1.35,18);
        easeProperty(gh.property("Opacity"),86);
    }

    // A brighter alignment line travels once through the frame.
    var scan=lineLayer("GRID_SCAN",0,540,W,540,C.green,2,0,-90);
    scan.property("Opacity").setValueAtTime(0,0);
    scan.property("Opacity").setValueAtTime(1.1,0);
    scan.property("Opacity").setValueAtTime(2.1,20);
    scan.property("Opacity").setValueAtTime(3.0,0);
    easeProperty(scan.property("Opacity"),88);

    // ------------------------------------------------------------
    // 03 — restrained depth particles
    // ------------------------------------------------------------
    for (var i=0;i<52;i++) {
        var p=comp.layers.addShape();
        p.name="PARTICLE_"+("00"+i).slice(-2);
        p.threeDLayer=true;
        var pg=p.property("Contents").addProperty("ADBE Vector Group");
        var pe=pg.property("Contents").addProperty("ADBE Vector Shape - Ellipse");
        var sz=2+(i%4);
        pe.property("Size").setValue([sz,sz]);
        var pf=pg.property("Contents").addProperty("ADBE Vector Graphic - Fill");
        pf.property("Color").setValue(i%9===0?C.green:C.muted);
        p.property("Opacity").setValue(10+(i%6)*4);
        var px=70+((i*347)%1780);
        var py=55+((i*193)%970);
        var pz=-500+((i*151)%1300);
        p.property("Position").setValueAtTime(0,[px,py,pz]);
        p.property("Position").setValueAtTime(DUR,[px+((i%5)-2)*42,py+((i%4)-2)*26,pz+((i%3)-1)*80]);
        easeProperty(p.property("Position"),76);
    }

    // ------------------------------------------------------------
    // 04 — cinematic camera: controlled push, arc and retreat
    // ------------------------------------------------------------
    var cam=comp.layers.addCamera("CAMERA_3D_CINEMATIC",[W/2,H/2]);
    cam.position.setValueAtTime(0,[960,540,2100]);
    cam.position.setValueAtTime(2.7,[1005,520,1550]);
    cam.position.setValueAtTime(6.0,[905,555,1120]);
    cam.position.setValueAtTime(9.0,[990,535,1320]);
    cam.position.setValueAtTime(12.4,[940,548,1450]);
    cam.position.setValueAtTime(16,[960,540,1750]);
    cam.pointOfInterest.setValueAtTime(0,[960,540,0]);
    cam.pointOfInterest.setValueAtTime(2.7,[1020,525,0]);
    cam.pointOfInterest.setValueAtTime(6,[910,550,0]);
    cam.pointOfInterest.setValueAtTime(9,[960,540,0]);
    cam.pointOfInterest.setValueAtTime(12.4,[900,540,0]);
    cam.pointOfInterest.setValueAtTime(16,[960,540,0]);
    easeProperty(cam.position,84);
    easeProperty(cam.pointOfInterest,86);

    // Soft point light adds a real 3D falloff cue to the UI plane.
    var key=comp.layers.addLight("KEY_LIGHT",[1360,300]);
    key.lightType=LightType.POINT;
    key.property("Intensity").setValue(38);
    key.property("Color").setValue(C.green);
    key.property("Position").setValue([1380,280,-450]);

    // ------------------------------------------------------------
    // 05 — HERO typography: stagger + slight depth
    // ------------------------------------------------------------
    var eyebrow=textLayer("HERO_EYEBROW","CAÇANDO OPORTUNIDADES  •  BRASIL",22,C.green,150,190,80,"Bold");
    var titleA=textLayer("HERO_TITLE_A","Dados reais.",94,C.text,150,320,50,"Bold");
    var titleB=textLayer("HERO_TITLE_B","Decisões inteligentes.",94,C.green,150,420,50,"Bold");
    var sub=textLayer("HERO_SUB","Inteligência imobiliária local-first para quem transforma\ninformação territorial em oportunidade.",29,C.muted,150,555,60,"Regular");

    opacityIn(eyebrow,.10,.65);
    opacityIn(titleA,.28,1.05);
    opacityIn(titleB,.42,1.20);
    opacityIn(sub,.72,1.55);
    scaleIn(titleA,.28,1.05,97);
    scaleIn(titleB,.42,1.20,97);

    // Micro tracking-like movement.
    move(titleA,.28,1.05,[164,324,85],[150,320,50]);
    move(titleB,.42,1.20,[166,424,85],[150,420,50]);

    // ------------------------------------------------------------
    // 06 — PRODUCT UI: material card with layered depth
    // ------------------------------------------------------------
    var shell=roundedRect("PRODUCT_SHELL",1080,590,C.panel,1390,555,-120,28);
    opacityIn(shell,1.20,1.75);
    scaleIn(shell,1.20,1.75,92);
    move(shell,1.20,1.75,[1460,585,-40],[1390,555,-120]);

    var shellLine=roundedRect("PRODUCT_EDGE",1080,590,[0.05,0.12,0.18],1390,555,-125,28);
    shellLine.property("Opacity").setValue(35);

    var bar=roundedRect("UI_TOPBAR",1080,70,C.panel2,1390,300,-95,18);
    var appName=textLayer("UI_APP_NAME","ImobHunter-BR  •  Pesquisa imobiliária",20,C.text,900,306,-70,"Bold");
    opacityIn(bar,1.45,1.80); opacityIn(appName,1.50,1.85);

    var field=roundedRect("UI_SEARCH",920,66,hex("#0C1A28"),1390,420,-70,14);
    var fieldText=textLayer("UI_SEARCH_TEXT","Endereço, número, quadra ou lote",18,C.muted,930,426,-55,"Regular");
    var badge=roundedRect("UI_BADGE",125,44,C.green,1820,420,-45,11);
    var badgeText=textLayer("UI_BADGE_TEXT","VISUAL",14,C.black,1783,425,-35,"Bold");
    opacityIn(field,1.75,2.10); opacityIn(fieldText,1.82,2.12);
    opacityIn(badge,1.90,2.25); opacityIn(badgeText,1.95,2.28);

    // Search cursor — a tiny premium detail.
    var cursor=roundedRect("SEARCH_CURSOR",2,26,C.green,930,428,-45,1);
    cursor.property("Opacity").setValue(0);
    cursor.property("Opacity").setValueAtTime(2.2,100);
    cursor.property("Opacity").setValueAtTime(2.7,0);
    cursor.property("Opacity").setValueAtTime(3.0,100);
    cursor.property("Opacity").setValueAtTime(3.5,0);

    var labels=["FONTES","COBERTURA","PROCESSAMENTO","PROVENIÊNCIA"];
    var vals=["15+","BR","LOCAL","100%"];
    var cols=[C.green,C.blue,C.pink,hex("#73E4A1")];

    for (var c=0;c<4;c++) {
        var cx=990+c*255;
        var card=roundedRect("UI_CARD_"+c,225,130,C.panel2,cx,555,-50,14);
        var lab=textLayer("UI_CARD_LABEL_"+c,labels[c],12,C.muted,cx-94,535,-35,"Bold");
        var val=textLayer("UI_CARD_VALUE_"+c,vals[c],38,cols[c],cx-94,595,-35,"Bold");
        opacityIn(card,2.05+c*.12,2.45+c*.12);
        opacityIn(lab,2.12+c*.12,2.48+c*.12);
        opacityIn(val,2.20+c*.12,2.58+c*.12);
        scaleIn(card,2.05+c*.12,2.45+c*.12,94);
    }

    // ------------------------------------------------------------
    // 07 — narrative transition: interface -> evidence network
    // ------------------------------------------------------------
    var narrative=textLayer("NARRATIVE","Uma fonte isolada é informação.\nVárias fontes reconciliadas viram inteligência.",48,C.text,150,775,30,"Bold");
    opacityIn(narrative,4.05,4.80);

    var chips=["GeoSampa","IBGE/CNEFE","SINTER/CIB","SNCR","SICAR","SIGEF","CNIR","CNPJ","ICMBio","IPHAN","OSM","IPTU"];
    for (var k=0;k<chips.length;k++) {
        var col=k%4, row=Math.floor(k/4);
        var xx=275+col*260, yy=860+row*70;
        var chip=roundedRect("SOURCE_"+k,215,44,k%4===0?hex("#102B1E"):C.panel2,xx,yy,10,22);
        var ct=textLayer("SOURCE_TEXT_"+k,chips[k],14,k%4===0?C.green:C.muted,xx-86,yy+6,22,"Bold");
        opacityIn(chip,4.45+k*.07,4.82+k*.07);
        opacityIn(ct,4.52+k*.07,4.89+k*.07);
        scaleIn(chip,4.45+k*.07,4.82+k*.07,94);
    }

    // Evidence constellation: points and connecting lines emerge behind the labels.
    var nodes=[
        [1120,705],[1280,650],[1450,720],[1600,655],[1740,745],
        [1210,840],[1390,820],[1560,875],[1710,830]
    ];
    for (var n=0;n<nodes.length;n++) {
        var dot=roundedRect("EVIDENCE_NODE_"+n,8,8,C.green,nodes[n][0],nodes[n][1],-5,4);
        opacityIn(dot,5.0+n*.08,5.25+n*.08);
    }
    var links=[
        [0,1],[1,2],[2,3],[3,4],[0,5],[1,6],[2,6],[3,7],[4,8],[5,6],[6,7],[7,8]
    ];
    for (var q=0;q<links.length;q++) {
        var a=nodes[links[q][0]], b=nodes[links[q][1]];
        var ln=lineLayer("EVIDENCE_LINK_"+q,a[0],a[1],b[0],b[1],C.line,1,0,-15);
        ln.property("Opacity").setValueAtTime(5.0+q*.04,0);
        ln.property("Opacity").setValueAtTime(5.35+q*.04,28);
        easeProperty(ln.property("Opacity"),84);
    }

    // ------------------------------------------------------------
    // 08 — dossier reveal: one property becomes a complete picture
    // ------------------------------------------------------------
    var dossier=roundedRect("DOSSIER_PANEL",980,520,C.panel,960,550,-40,24);
    dossier.property("Opacity").setValue(0);
    dossier.property("Position").setValueAtTime(6.2,[1000,580,-10]);
    dossier.property("Position").setValueAtTime(7.0,[960,550,-40]);
    dossier.property("Opacity").setValueAtTime(6.2,0);
    dossier.property("Opacity").setValueAtTime(7.0,100);
    easeProperty(dossier.property("Position"),86);
    easeProperty(dossier.property("Opacity"),86);

    var dTitle=textLayer("DOSSIER_TITLE","DOSSIÊ CONSOLIDADO",18,C.green,520,335,-20,"Bold");
    var dMain=textLayer("DOSSIER_MAIN","Imóvel identificado",48,C.text,520,405,-15,"Bold");
    var dSub=textLayer("DOSSIER_SUB","Endereço • cadastro • área • coordenadas • fontes • confiança",19,C.muted,520,455,-10,"Regular");
    opacityIn(dTitle,6.55,6.95); opacityIn(dMain,6.70,7.15); opacityIn(dSub,6.85,7.30);

    var confidence=roundedRect("CONFIDENCE",250,76,hex("#102B1E"),1480,430,-5,16);
    var confidenceText=textLayer("CONFIDENCE_TEXT","CONFIANÇA  •  ALTA",15,C.green,1405,437,10,"Bold");
    opacityIn(confidence,7.05,7.45); opacityIn(confidenceText,7.12,7.52);

    var dLines=["IDENTIFICAÇÃO","ENDEREÇO","ÁREA / TERRENO","COORDENADAS","PROVENIÊNCIA"];
    for (var dl=0;dl<dLines.length;dl++) {
        var dy=525+dl*48;
        var lab2=textLayer("DOSSIER_LABEL_"+dl,dLines[dl],11,C.muted,520,dy,-10,"Bold");
        var line2=roundedRect("DOSSIER_VALUE_"+dl,480,28,C.panel2,800,dy-4,-5,8);
        opacityIn(lab2,7.10+dl*.08,7.38+dl*.08);
        opacityIn(line2,7.15+dl*.08,7.43+dl*.08);
    }

    // ------------------------------------------------------------
    // 09 — payoff: simplify aggressively
    // ------------------------------------------------------------
    var payoff=textLayer("PAYOFF","Caçando oportunidades.",82,C.text,150,300,35,"Bold");
    var payoffBrand=textLayer("PAYOFF_BRAND","ImobHunter-BR",34,C.green,150,390,35,"Bold");
    opacityIn(payoff,10.0,10.75);
    opacityIn(payoffBrand,10.30,10.95);
    scaleIn(payoff,10.0,10.75,97);

    var cta=roundedRect("CTA",330,70,C.green,315,515,30,16);
    var ctaText=textLayer("CTA_TEXT","CONHECER A PLATAFORMA",17,C.black,175,523,40,"Bold");
    opacityIn(cta,10.75,11.25);
    opacityIn(ctaText,10.82,11.30);

    // Brand mark — minimal, not a second logo system.
    var mark=roundedRect("BRAND_MARK",90,90,C.panel2,1735,885,40,22);
    var markText=textLayer("BRAND_MARK_TEXT","IH",26,C.green,1710,895,50,"Bold");
    opacityIn(mark,10.55,11.05);
    opacityIn(markText,10.65,11.15);

    // ------------------------------------------------------------
    // 10 — outro: camera breathes, UI disappears, brand remains
    // ------------------------------------------------------------
    move(payoff,12.2,15.5,[150,300,35],[150,285,70]);
    move(payoffBrand,12.2,15.5,[150,390,35],[150,375,70]);
    move(cta,12.2,15.5,[315,515,30],[315,500,65]);
    move(ctaText,12.2,15.5,[175,523,40],[175,508,75]);
    move(mark,12.2,15.5,[1735,885,40],[1735,870,80]);
    move(markText,12.2,15.5,[1710,895,50],[1710,880,90]);

    // Fade the full film gently rather than hard-cutting.
    var fade=comp.layers.addSolid(C.bg,"OUTRO_FADE",W,H,1);
    fade.property("Opacity").setValueAtTime(14.9,0);
    fade.property("Opacity").setValueAtTime(16,100);
    easeProperty(fade.property("Opacity"),88);

    // ------------------------------------------------------------
    // 11 — markers / handoff notes
    // ------------------------------------------------------------
    var markers=[
        [0.00,"OPEN — atmosphere / grid / particles / camera push"],
        [1.20,"HERO — typography enters with long ease"],
        [1.75,"PRODUCT — UI material reveal / parallax"],
        [4.05,"INTELLIGENCE — source constellation"],
        [6.20,"DOSSIER — evidence becomes consolidated property"],
        [10.00,"PAYOFF — simplify / brand statement"],
        [10.75,"CTA — restrained product invitation"],
        [14.90,"OUTRO — cinematic fade"]
    ];
    for (var m=0;m<markers.length;m++) {
        comp.markerProperty.setValueAtTime(markers[m][0],new MarkerValue(markers[m][1]));
    }

    comp.workAreaStart=0;
    comp.workAreaDuration=DUR;

    app.endUndoGroup();
    alert("ImobHunter-BR Cinematic V2 criado: IMOBHUNTER_CINEMATIC_V2_16S");
})();
