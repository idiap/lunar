// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";

function pdfUrl(slide) {
  const bytes = Uint8Array.from(atob(slide.content_base64), (character) => character.charCodeAt(0));
  return URL.createObjectURL(new Blob([bytes], { type: slide.media_type }));
}

export function SlidesView({ project }) {
  const slide = project.slides?.[0] || null;
  const [page, setPage] = useState(0);
  const downloadUrl = useMemo(() => slide ? pdfUrl(slide) : "", [slide]);

  useEffect(() => {
    setPage(0);
    return () => { if (downloadUrl) URL.revokeObjectURL(downloadUrl); };
  }, [downloadUrl]);

  useEffect(() => {
    if (!slide) return undefined;
    const navigate = (event) => {
      if (event.key === "ArrowLeft") setPage((value) => Math.max(0, value - 1));
      if (event.key === "ArrowRight") setPage((value) => Math.min(slide.pages_base64.length - 1, value + 1));
    };
    document.addEventListener("keydown", navigate);
    return () => document.removeEventListener("keydown", navigate);
  }, [slide]);

  if (!slide) {
    return (
      <section className="slides-panel" role="tabpanel" aria-labelledby="slides-tab">
        <div className="slides-heading">
          <div>
            <p className="eyebrow">PROJECT PRESENTATION</p>
            <h2>{project.label} slides</h2>
            <p>Presentation material has not been added for this project.</p>
          </div>
        </div>
        <div className="slides-empty">
          <strong>No slide deck is available for this project yet.</strong>
          <span>This public Lunar module does not include an authored slide deck.</span>
        </div>
      </section>
    );
  }

  const lastPage = slide.pages_base64.length - 1;
  return (
    <section className="slides-panel" role="tabpanel" aria-labelledby="slides-tab">
      <div className="slides-heading">
        <div>
          <p className="eyebrow">PROJECT PRESENTATION</p>
          <h2>{slide.title}</h2>
          <p>Embedded PDF presentation · {slide.file_name}</p>
        </div>
        <a className="slides-download" href={downloadUrl} download={slide.file_name}>Open or download PDF</a>
      </div>
      <div className="slides-stage">
        <Button
          variant="outline"
          size="icon"
          className="slide-nav slide-nav-prev"
          onClick={() => setPage((value) => Math.max(0, value - 1))}
          disabled={page === 0}
          aria-label="Previous slide"
        >
          <ChevronLeft aria-hidden="true" />
        </Button>
        <img
          className="slides-image"
          src={`data:image/jpeg;base64,${slide.pages_base64[page]}`}
          alt={`${slide.title}, slide ${page + 1} of ${lastPage + 1}`}
        />
        <Button
          variant="outline"
          size="icon"
          className="slide-nav slide-nav-next"
          onClick={() => setPage((value) => Math.min(lastPage, value + 1))}
          disabled={page === lastPage}
          aria-label="Next slide"
        >
          <ChevronRight aria-hidden="true" />
        </Button>
      </div>
      <div className="slides-footer">
        <span className="slides-counter">Slide {page + 1} of {lastPage + 1}</span>
        <span>Use the arrow buttons or keyboard arrow keys to navigate.</span>
      </div>
    </section>
  );
}
