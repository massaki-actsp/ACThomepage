const videoState = {
  items: [],
  selected: null,
};

const paths = {
  image: (fileName) => `${document.querySelector('[data-video-page]').dataset.imageBase}${encodeURIComponent(fileName)}`,
  video: (fileName) => `/media/mural/${encodeURIComponent(fileName)}`,
};

function safeText(value, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function safeNumber(value, fallback = 0) {
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

function recordVideoClick(video, source) {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  const eventId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  fetch("/api/mural/clicks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_id: video.id, source, event_id: eventId }),
    keepalive: true,
  }).catch(() => {});
}

function normalizeVideo(item) {
  return {
    id: safeNumber(item.id),
    title: safeText(item.title, "Vídeo sem título"),
    description: safeText(item.description, "Descrição indisponível."),
    category: safeText(item.category, "Geral"),
    year: safeNumber(item.year, new Date().getFullYear()),
    duration: safeText(item.duration, "0 min"),
    rating: safeText(item.rating, "Livre"),
    poster: safeText(item.poster, "banner.jpg"),
    banner: safeText(item.banner, "banner.jpg"),
    video: safeText(item.video, ""),
    provider: safeText(item.provider, "local"),
    embedUrl: safeText(item.embed_url, ""),
    externalUrl: safeText(item.external_url, ""),
    caption: safeText(item.caption, ""),
    featured: Boolean(item.featured),
    openOnSelect: Boolean(item.open_on_select),
  };
}

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) {
    element.textContent = value;
  }
}

function setSelectedVideo(video, scrollToHero = false) {
  videoState.selected = video;
  localStorage.setItem("actsp:last-mural-item", String(video.id));

  setText("[data-video-title]", video.title);
  setText("[data-video-description]", video.description);
  setText("[data-video-year]", String(video.year));
  setText("[data-video-duration]", video.duration);
  setText("[data-video-category]", video.category);
  setText("[data-video-rating]", video.rating);
  setText("[data-player-title]", video.title);
  setText("[data-player-description]", video.description);
  const playButton = document.querySelector("[data-open-player]");
  if (playButton?.lastChild) {
    playButton.lastChild.textContent = video.provider === "external" ? " Acessar site" : " Assistir agora";
  }

  const heroImage = document.querySelector("[data-hero-image]");
  const heroVideo = document.querySelector("[data-hero-video]");

  if (heroImage) {
    heroImage.src = paths.image(video.banner);
  }

  if (heroVideo) {
    heroVideo.pause();
    heroVideo.replaceChildren();
    heroVideo.hidden = video.provider !== "local";
    heroVideo.poster = paths.image(video.banner);

    if (video.provider === "local" && video.video) {
      const source = document.createElement("source");
      source.src = paths.video(video.video);
      source.type = "video/mp4";
      heroVideo.append(source);
      heroVideo.load();
      heroVideo.play().catch(() => {
        heroVideo.hidden = true;
      });
    }
  }

  document.querySelectorAll("[data-video-card]").forEach((card) => {
    card.classList.toggle("is-selected", Number(card.dataset.videoCard) === video.id);
  });

  if (scrollToHero && window.matchMedia("(max-width: 720px)").matches) {
    document.querySelector("[data-video-hero]")?.scrollIntoView({ behavior: "smooth" });
  }
}

function createVideoCard(video, mode = "poster") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = mode === "poster" ? "video-poster-card" : "video-list-card";
  button.dataset.videoCard = String(video.id);
  button.setAttribute("aria-label", video.provider === "external"
    ? `Acessar site ${video.title}` : `Selecionar vídeo ${video.title}`);

  const image = document.createElement("img");
  image.src = paths.image(video.poster);
  image.alt = `Capa do vídeo ${video.title}`;
  image.loading = "lazy";
  image.addEventListener("error", () => {
    image.src = paths.image("banner.jpg");
  });

  const overlay = document.createElement("span");
  overlay.className = "video-play-overlay";
  overlay.setAttribute("aria-hidden", "true");

  const icon = document.createElement("i");
  icon.className = "fa fa-play";
  overlay.append(icon);

  const body = document.createElement("span");
  body.className = "video-card-body";

  const title = document.createElement("strong");
  title.textContent = video.title;

  const meta = document.createElement("span");
  meta.textContent = `${video.category} | ${video.duration} | ${video.year}`;

  body.append(title, meta);
  button.append(image, overlay, body);
  button.addEventListener("click", () => {
    setSelectedVideo(video, true);
    recordVideoClick(video, mode === "poster" ? "carousel" : "catalog");
    if (video.provider === "external" || video.openOnSelect) openPlayer();
  });
  return button;
}

function renderCarousel(items) {
  const carousel = document.querySelector("[data-video-carousel]");
  if (!carousel) {
    return;
  }
  carousel.replaceChildren(...items.map((video) => createVideoCard(video, "poster")));
}

function renderGrid(items) {
  const grid = document.querySelector("[data-video-grid]");
  const empty = document.querySelector("[data-video-empty]");
  if (!grid || !empty) {
    return;
  }
  grid.replaceChildren(...items.map((video) => createVideoCard(video, "list")));
  empty.hidden = items.length > 0;
}

function applyFilters() {
  const form = document.querySelector("[data-video-filters]");
  if (!form) {
    renderGrid(videoState.items);
    return;
  }

  const data = new FormData(form);
  const search = safeText(data.get("search")?.toString()).toLowerCase();
  const category = safeText(data.get("category")?.toString());
  const sort = safeText(data.get("sort")?.toString(), "title");

  const filtered = videoState.items
    .filter((video) => !search || video.title.toLowerCase().includes(search))
    .filter((video) => !category || video.category === category)
    .sort((first, second) => {
      if (sort === "year") {
        return second.year - first.year;
      }
      if (sort === "duration") {
        return parseInt(first.duration, 10) - parseInt(second.duration, 10);
      }
      return first.title.localeCompare(second.title, "pt-BR");
    });

  renderGrid(filtered);
}

function openPlayer() {
  const dialog = document.querySelector("[data-video-dialog]");
  const player = document.querySelector("[data-player-video]");
  const embedWrap = document.querySelector("[data-player-embed-wrap]");
  const embed = document.querySelector("[data-player-embed]");
  const video = videoState.selected;

  if (video?.provider === "external") {
    try {
      const url = new URL(video.externalUrl);
      if (url.protocol === "https:" && url.host === "aguaviva.actsp.com.br"
          && !url.username && !url.password) {
        window.location.assign(url.href);
      }
    } catch {
      // Invalid catalog links must never trigger navigation.
    }
    return;
  }

  if (!dialog || !player || !video) {
    return;
  }

  player.pause();
  player.replaceChildren();
  player.hidden = true;

  if (embed) {
    embed.removeAttribute("src");
  }
  if (embedWrap) {
    embedWrap.hidden = true;
  }

  if (["youtube", "vimeo"].includes(video.provider) && video.embedUrl && embed && embedWrap) {
    const embedUrl = new URL(video.embedUrl);
    const trustedEmbed = embedUrl.protocol === "https:" && (
      (video.provider === "youtube" && embedUrl.hostname === "www.youtube.com" && embedUrl.pathname.startsWith("/embed/"))
      || (video.provider === "vimeo" && embedUrl.hostname === "player.vimeo.com" && embedUrl.pathname.startsWith("/video/"))
    );
    if (!trustedEmbed) return;
    embedUrl.searchParams.set("autoplay", "1");
    if (video.provider === "youtube") {
      embedUrl.searchParams.set("rel", "0");
    } else {
      embedUrl.searchParams.set("dnt", "1");
    }
    embed.src = embedUrl.toString();
    embed.title = `Player do vídeo ${video.title}`;
    embedWrap.hidden = false;
  } else if (video.video) {
    player.hidden = false;
    player.muted = false;
    player.volume = 1;

    const source = document.createElement("source");
    source.src = paths.video(video.video);
    source.type = "video/mp4";
    player.append(source);

    if (video.caption) {
      const track = document.createElement("track");
      track.kind = "captions";
      track.label = "Português";
      track.srclang = "pt-BR";
      track.src = paths.video(video.caption);
      player.append(track);
    }

    player.load();
  } else {
    return;
  }

  dialog.showModal();
  document.body.classList.add("is-video-modal-open");

  if (!player.hidden) {
    player.play().catch(() => {});
  }
}

function closePlayer() {
  const dialog = document.querySelector("[data-video-dialog]");
  const player = document.querySelector("[data-player-video]");
  const embed = document.querySelector("[data-player-embed]");

  if (player) {
    player.pause();
  }
  if (embed) {
    embed.removeAttribute("src");
  }
  if (dialog?.open) {
    dialog.close();
  }

  document.body.classList.remove("is-video-modal-open");
}

function bindControls() {
  document.querySelector("[data-open-player]")?.addEventListener("click", () => {
    openPlayer();
    if (videoState.selected) recordVideoClick(videoState.selected, "player");
  });
  document.querySelector("[data-open-details]")?.addEventListener("click", () => {
    document.querySelector("#catalogo")?.scrollIntoView({ behavior: "smooth" });
  });
  document.querySelector("[data-close-player]")?.addEventListener("click", closePlayer);
  document.querySelector("[data-video-dialog]")?.addEventListener("cancel", closePlayer);

  document.querySelector("[data-carousel-prev]")?.addEventListener("click", () => {
    document.querySelector("[data-video-carousel]")?.scrollBy({ left: -360, behavior: "smooth" });
  });
  document.querySelector("[data-carousel-next]")?.addEventListener("click", () => {
    document.querySelector("[data-video-carousel]")?.scrollBy({ left: 360, behavior: "smooth" });
  });

  document.querySelector("[data-video-filters]")?.addEventListener("input", applyFilters);
  document.querySelector("[data-video-filters]")?.addEventListener("submit", (event) => {
    event.preventDefault();
  });

  document.querySelector("[data-toggle-hero-audio]")?.addEventListener("click", (event) => {
    const heroVideo = document.querySelector("[data-hero-video]");
    if (!heroVideo) {
      return;
    }

    heroVideo.muted = !heroVideo.muted;
    heroVideo.volume = 1;
    event.currentTarget.setAttribute(
      "aria-label",
      heroVideo.muted ? "Ativar áudio do vídeo em destaque" : "Desativar áudio do vídeo em destaque",
    );
    event.currentTarget.querySelector("i").className = heroVideo.muted ? "fa fa-volume-off" : "fa fa-volume-up";
  });

  document.querySelector("[data-toggle-hero-play]")?.addEventListener("click", (event) => {
    const heroVideo = document.querySelector("[data-hero-video]");
    if (!heroVideo) {
      return;
    }

    if (heroVideo.paused) {
      heroVideo.play().catch(() => {});
      event.currentTarget.querySelector("i").className = "fa fa-pause";
    } else {
      heroVideo.pause();
      event.currentTarget.querySelector("i").className = "fa fa-play";
    }
  });

  document.querySelector("[data-video-header] .video-menu-toggle")?.addEventListener("click", (event) => {
    const nav = document.querySelector("#video-nav");
    const isOpen = nav?.classList.toggle("is-open") || false;
    event.currentTarget.setAttribute("aria-expanded", String(isOpen));
  });

  window.addEventListener("scroll", () => {
    document.querySelector("[data-video-header]")?.classList.toggle("is-scrolled", window.scrollY > 12);
  });

  bindVideoTabBar();
}

function bindVideoTabBar() {
  new App(".app");
}

class App {
  constructor(qs) {
    this.el = document.querySelector(qs);
    this.page = 1;
    this.el?.addEventListener("click", this.viewPage.bind(this));
  }

  setPage(number) {
    const nav = document.querySelector("[data-nav]");
    nav?.classList.remove(`nav--tilt${this.page}`);
    this.page = number;
    nav?.classList.add(`nav--tilt${this.page}`);
  }

  viewPage(event) {
    let parent = event.target;

    while (parent && !parent.hasAttribute("data-nav-item")) {
      parent = parent.parentElement;
    }

    if (!parent) {
      return;
    }

    event.preventDefault();
    const pageNumber = Number(parent.getAttribute("data-nav-item"));

    if (pageNumber !== this.page) {
      this.setPage(pageNumber);

      const items = document.querySelectorAll("[data-nav-item]");
      Array.from(items).forEach((item) => {
        item.removeAttribute("aria-describedby");
        item.classList.remove("active");
        item.querySelector("svg")?.classList.remove("active-fill");
      });

      parent.setAttribute("aria-describedby", "current");
      parent.classList.add("active");
      parent.querySelector("svg")?.classList.add("active-fill");
      this.spawnCards();
    }

    const anchor = parent.querySelector("a");
    const target = anchor?.getAttribute("href");
    if (target?.startsWith("#")) {
      document.querySelector(target)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    document.querySelector("#video-nav")?.classList.remove("is-open");
    document.querySelector("[data-video-header] .video-menu-toggle")?.setAttribute("aria-expanded", "false");
  }

  spawnCards() {
    const flyOut = "card--fly-out";
    const cards = document.querySelectorAll("[data-card]");

    Array.from(cards).forEach((card) => {
      card.classList.remove(flyOut);
      void card.offsetWidth;
      card.classList.add(flyOut);
    });
  }
}

async function initVideos() {
  const response = await fetch("/api/mural");
  const payload = await response.json();
  videoState.items = Array.isArray(payload.items) ? payload.items.map(normalizeVideo) : [];

  const storedId = Number(localStorage.getItem("actsp:last-mural-item"));
  const featured = videoState.items.find((item) => item.id === storedId)
    || videoState.items.find((item) => item.featured)
    || videoState.items[0];

  renderCarousel(videoState.items);
  renderGrid(videoState.items);

  if (featured) {
    setSelectedVideo(featured);
  }

  bindControls();
}

if (document.querySelector("[data-video-page]")) {
  initVideos().catch(() => {
    setText("[data-video-title]", "Mural indisponível");
    setText("[data-video-description]", "Não foi possível carregar o catálogo do mural neste momento.");
  });
}
