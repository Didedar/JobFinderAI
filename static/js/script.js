document.addEventListener('DOMContentLoaded', function() {
    // Инициализация AOS, если библиотека подключена
    if (typeof AOS !== 'undefined') {
        AOS.init({
            duration: 800,
            once: true
        });
    }

    // Инициализация Swiper, если библиотека подключена
    if (typeof Swiper !== 'undefined') {
        new Swiper('.swiper-container', {
            slidesPerView: 1,
            spaceBetween: 40,
            pagination: {
                el: '.swiper-pagination',
                clickable: true
            },
            breakpoints: {
                768: { slidesPerView: 2 },
                1024: { slidesPerView: 3 }
            }
        });
    }

    // Отключение стандартного поведения у ссылок навигации
    document.querySelectorAll('.nav-links a, .footer-links a').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
        });
    });

    // Элементы для загрузки резюме и отображения вакансий
    const uploadArea = document.getElementById('uploadArea');
    const resumeInput = document.getElementById('resumeInput');
    const jobCardsContainer = document.getElementById('jobCardsContainer');
    const jobCardTemplate = document.getElementById('jobCardTemplate'); // Если используется шаблон
    const jobListingsSection = document.getElementById('jobListingsSection');
    const modal = document.getElementById('detailedModal');
    const closeModal = modal ? modal.querySelector('.close-modal') : null;
    const countrySelect = document.getElementById('countrySelect');

    // Скрытие секции вакансий при загрузке
    if (jobListingsSection) {
        jobListingsSection.style.display = 'none';
    }

    // Загрузка списка стран из API HeadHunter (добавляем проверку на существование countrySelect)
    if (countrySelect) {
        fetch('https://api.hh.ru/areas')
            .then(response => {
                if (!response.ok) throw new Error('Failed to fetch countries');
                return response.json();
            })
            .then(areas => {
                populateCountrySelect(areas, countrySelect);
            })
            .catch(error => {
                console.error('Error fetching countries:', error);
                countrySelect.innerHTML = '<option value="">Error loading countries</option>';
            });
    }

    // Функция заполнения выпадающего списка стран
    function populateCountrySelect(areas, selectElement) {
        if (!selectElement) return;
        
        areas.forEach(area => {
            const option = document.createElement('option');
            option.value = area.id;
            option.textContent = area.name;
            selectElement.appendChild(option);

            if (area.areas && area.areas.length > 0) {
                area.areas.forEach(subArea => {
                    const subOption = document.createElement('option');
                    subOption.value = subArea.id;
                    subOption.textContent = `${area.name} - ${subArea.name}`;
                    selectElement.appendChild(subOption);
                });
            }
        });
    }

    // Обработчики для загрузки резюме
    if (uploadArea && resumeInput) {
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });

        uploadArea.addEventListener('drop', handleDrop);
        resumeInput.addEventListener('change', handleFileChange);
    }

    function handleDrop(e) {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            uploadResume(files[0]);
        }
    }

    function handleFileChange() {
        if (resumeInput.files.length > 0) {
            uploadResume(resumeInput.files[0]);
        }
    }

    // Функция загрузки резюме с отображением индикатора и обработкой ответа сервера
    function uploadResume(file) {
        if (!uploadArea || !countrySelect) return;
        
        const selectedCountryId = countrySelect.value;
        if (!selectedCountryId) {
            showErrorMessage('Please select a country before uploading your resume.');
            return;
        }

        sessionStorage.setItem('location', selectedCountryId);  // Save location
        uploadArea.classList.add('uploading');

        // Create loader element
        const loader = document.createElement('div');
        loader.className = 'upload-loader';
        loader.innerHTML = `
            <div class="loader-icon"></div>
            <div class="loader-text">Analyzing your resume...</div>
        `;
        uploadArea.appendChild(loader);

        // Create progress bar
        const progress = document.createElement('div');
        progress.className = 'upload-progress';
        uploadArea.appendChild(progress);

        // Simulate progress (since actual progress might not be available)
        let width = 0;
        const progressInterval = setInterval(() => {
            if (width >= 90) clearInterval(progressInterval);
            width = Math.min(90, width + 1);
            progress.style.width = width + '%';
        }, 50);

        const formData = new FormData();
        formData.append('resume', file);
        formData.append('location', selectedCountryId);

        console.log('Sending file to server:', file.name);

        fetch('/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            console.log('Response status:', response.status);
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.error || `Server error: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            // Complete the progress bar
            clearInterval(progressInterval);
            progress.style.width = '100%';

            setTimeout(() => {
                uploadArea.classList.remove('uploading');
                if (uploadArea.contains(loader)) uploadArea.removeChild(loader);
                if (uploadArea.contains(progress)) uploadArea.removeChild(progress);

                if (data.error) {
                    throw new Error(data.error);
                }

                // Сохраняем текст резюме для последующего использования
                window.resumeText = data.resume_text;

                if (data.profession && data.profession.profession_ru) {
                    // Отображаем обнаруженную профессию
                    showSuccessMessage(`Resume successfully uploaded! Detected profession: ${data.profession.profession_ru}`);
                }

                if (Array.isArray(data.vacancies) && data.vacancies.length > 0) {
                    displayVacancies(data.vacancies);
                    if (jobListingsSection) {
                        jobListingsSection.style.display = 'block';
                        // Прокручиваем к секции с вакансиями
                        jobListingsSection.scrollIntoView({ behavior: 'smooth' });
                    }
                } else {
                    showNoVacanciesMessage();
                }
            }, 500);
        })
        .catch(error => {
            clearInterval(progressInterval);
            uploadArea.classList.remove('uploading');
            if (uploadArea.contains(loader)) uploadArea.removeChild(loader);
            if (uploadArea.contains(progress)) uploadArea.removeChild(progress);
            showErrorMessage(error.message || 'An error occurred during upload.');
        });
    }

    function showSuccessMessage(message) {
        const alert = document.createElement('div');
        alert.className = 'upload-alert success';
        alert.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
            ${message}
        `;
        document.body.appendChild(alert);
        
        // Remove alert with fade out animation
        setTimeout(() => {
            alert.style.animation = 'fadeOut 0.5s ease-out forwards';
            setTimeout(() => {
                if (document.body.contains(alert)) {
                    document.body.removeChild(alert);
                }
            }, 500);
        }, 4500);
    }

    function showErrorMessage(message) {
        const alert = document.createElement('div');
        alert.className = 'upload-alert error';
        alert.textContent = `Error: ${message}. Please try again.`;
        
        if (uploadArea) {
            uploadArea.appendChild(alert);
            setTimeout(() => {
                if (uploadArea.contains(alert)) {
                    uploadArea.removeChild(alert);
                }
            }, 5000);
        } else {
            document.body.appendChild(alert);
            setTimeout(() => {
                if (document.body.contains(alert)) {
                    document.body.removeChild(alert);
                }
            }, 5000);
        }
    }

    function showNoVacanciesMessage() {
        if (jobCardsContainer) {
            jobCardsContainer.innerHTML = '<p>No vacancies found. Try uploading a different resume.</p>';
        }
    }

    function displayVacancies(vacancies) {
        if (!jobCardsContainer || !jobCardTemplate) {
            console.error('Job cards container or template not found');
            return;
        }
        
        if (!window.originalVacancies) {
            window.originalVacancies = vacancies;
        }
        
        jobCardsContainer.innerHTML = '';
        
        if (!vacancies || vacancies.length === 0) {
            jobCardsContainer.innerHTML = '<p>No vacancies found.</p>';
            return;
        }
        
        // Сортировка по убыванию similarity_score
        vacancies.sort((a, b) => (b.similarity_score || 0) - (a.similarity_score || 0));
        
        vacancies.forEach(vacancy => {
            const originalVacancy = window.originalVacancies.find(v => v.id === vacancy.id);
            if (originalVacancy) {
                vacancy.similarity_score = originalVacancy.similarity_score;
            }
        
            const jobCard = jobCardTemplate.content ? 
                jobCardTemplate.content.cloneNode(true).firstElementChild : 
                jobCardTemplate.cloneNode(true);
                
            jobCard.style.display = 'block';
            
            const titleEl = jobCard.querySelector('.job-title');
            if (titleEl) titleEl.textContent = vacancy.title || 'Title not specified';
            
            const companyEl = jobCard.querySelector('.job-company');
            if (companyEl) companyEl.textContent = vacancy.company || 'Company not specified';
            
            const salaryText = formatSalary(vacancy.salary);
            const detailsEl = jobCard.querySelector('.job-details');
            if (detailsEl) detailsEl.textContent = `${vacancy.employment_type || 'Not specified'} | ${salaryText}`;
            
            const applyBtn = jobCard.querySelector('.job-apply-btn');
            if (applyBtn) applyBtn.href = vacancy.url || '#';
            
            const similarityEl = jobCard.querySelector('.job-similarity');
            if (similarityEl) similarityEl.textContent = `${Math.round((vacancy.similarity_score || 0) * 100)}%`;
        
            const detailedBtn = jobCard.querySelector('.job-detailed-btn');
            if (detailedBtn) {
                detailedBtn.setAttribute('data-vacancy-id', vacancy.id || '');
                detailedBtn.addEventListener('click', () => showDetailedView(vacancy));
            }
        
            const addToFavoritesBtn = jobCard.querySelector('.add-to-favorites');
            if (addToFavoritesBtn) {
                addToFavoritesBtn.setAttribute('data-vacancy-id', vacancy.id || '');
                addToFavoritesBtn.setAttribute('data-vacancy-title', vacancy.title || '');
                addToFavoritesBtn.setAttribute('data-vacancy-company', vacancy.company || '');
                addToFavoritesBtn.setAttribute('data-vacancy-url', vacancy.url || '');
                addToFavoritesBtn.setAttribute('data-employment-type', vacancy.employment_type || '');
                addToFavoritesBtn.setAttribute('data-salary-from', vacancy.salary?.from || '');
                addToFavoritesBtn.setAttribute('data-salary-to', vacancy.salary?.to || '');
                addToFavoritesBtn.setAttribute('data-salary-currency', vacancy.salary?.currency || '');
                addToFavoritesBtn.setAttribute('data-snippet', vacancy.snippet || '');
                addToFavoritesBtn.setAttribute('data-similarity-score', vacancy.similarity_score || 0);
                addToFavoritesBtn.setAttribute('data-location', vacancy.location || '');
                addToFavoritesBtn.setAttribute('data-experience-level', vacancy.experience_level || '');
            }
        
            jobCardsContainer.appendChild(jobCard);
        });
    }
    
    // Единый обработчик для добавления в избранное через делегирование событий
    if (jobCardsContainer) {
        jobCardsContainer.addEventListener('click', function(e) {
            if (!e.target.classList.contains('add-to-favorites')) return;
            
            const button = e.target;
            const vacancy = {
                vacancy_id: button.getAttribute('data-vacancy-id'),
                vacancy_title: button.getAttribute('data-vacancy-title'),
                vacancy_company: button.getAttribute('data-vacancy-company'),
                vacancy_url: button.getAttribute('data-vacancy-url'),
                employment_type: button.getAttribute('data-employment-type'),
                salary: {
                    from: parseWithDefault(button.getAttribute('data-salary-from')),
                    to: parseWithDefault(button.getAttribute('data-salary-to')),
                    currency: button.getAttribute('data-salary-currency')
                },
                snippet: button.getAttribute('data-snippet'),
                similarity_score: parseFloat(button.getAttribute('data-similarity-score') || 0),
                location: button.getAttribute('data-location'),
                experience_level: button.getAttribute('data-experience-level')
            };
    
            fetch('/add_to_favorites', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(vacancy)
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(data => {
                        throw new Error(data.error || 'Failed to add vacancy to favorites.');
                    });
                }
                return response.json();
            })
            .then(data => {
                showSuccessMessage(data.message || 'Vacancy added to favorites successfully.');
            })
            .catch(error => {
                console.error('Error:', error);
                showErrorMessage(error.message || 'An error occurred while adding the vacancy to favorites.');
            });
        });
    }

    // Helper function to safely parse numbers with fallback
    function parseWithDefault(value, defaultValue = null) {
        if (!value) return defaultValue;
        const parsed = parseInt(value, 10);
        return isNaN(parsed) ? defaultValue : parsed;
    }

    // Вспомогательная функция для форматирования зарплаты
    function formatSalary(salary) {
        if (!salary) return 'Salary not specified';
        
        let salaryStr = '';
        if (salary.from) {
            salaryStr += `from ${salary.from}`;
        }
        if (salary.to) {
            if (salaryStr) salaryStr += ' ';
            salaryStr += `to ${salary.to}`;
        }
        if (salary.currency) {
            salaryStr += ` ${salary.currency}`;
        }
        return salaryStr.trim() || 'Salary not specified';
    }

    // Настройка модального окна для детального просмотра вакансии
    if (closeModal && modal) {
        closeModal.addEventListener('click', () => {
            modal.style.display = 'none';
        });

        window.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    }

    function showDetailedView(vacancy) {
        if (!modal) {
            console.error('Modal window not found');
            return;
        }

        // Очищаем и заполняем модальное окно данными о вакансии
        const titleEl = modal.querySelector('.modal-title');
        if (titleEl) titleEl.textContent = vacancy.title || 'Job title';
        
        const companyEl = modal.querySelector('.modal-company');
        if (companyEl) companyEl.textContent = `Company: ${vacancy.company || 'Not specified'}`;
        
        // Форматируем детали вакансии для лучшей читаемости
        const detailsEl = modal.querySelector('.modal-details');
        if (detailsEl) {
            const snippet = vacancy.snippet || 'Description not available';
            const formattedSnippet = snippet
                .replace(/<highlighted>/g, '')
                .replace(/<\/highlighted>/g, '')
                .split('\n')
                .filter(line => line.trim())
                .join('\n\n');
            
            detailsEl.innerHTML = formattedSnippet;
        }
        
        // Форматируем остальную информацию
        const salaryEl = modal.querySelector('.modal-salary');
        if (salaryEl) salaryEl.textContent = `Salary: ${formatSalary(vacancy.salary)}`;
        
        const employmentEl = modal.querySelector('.modal-employment');
        if (employmentEl) employmentEl.textContent = `Employment type: ${vacancy.employment_type || 'Not specified'}`;
        
        const matchEl = modal.querySelector('.match-score');
        if (matchEl) matchEl.textContent = `Match with your resume: ${Math.round((vacancy.similarity_score || 0) * 100)}%`;

        // Настраиваем кнопку для перехода к вакансии
        const applyBtn = modal.querySelector('.apply-btn');
        if (applyBtn) {
            applyBtn.href = vacancy.url || '#';
        }

        // Показываем индикатор загрузки анализа
        const analysisLoader = modal.querySelector('.analysis-loader');
        const analysisContent = modal.querySelector('.analysis-content');
        if (analysisLoader) analysisLoader.style.display = 'block';
        if (analysisContent) analysisContent.style.display = 'none';

        modal.style.display = 'block';

        // Запрос на анализ соответствия резюме вакансии
        fetch('/analyze-match', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                vacancy: vacancy,
                similarity_score: vacancy.similarity_score,
                resume_text: window.resumeText || ''
            })
        })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            return response.json();
        })
        .then(analysis => {
            if (analysisLoader) analysisLoader.style.display = 'none';
            if (analysisContent) analysisContent.style.display = 'block';

            const recommendation = modal.querySelector('.recommendation');
            if (recommendation) {
                // Форматируем оценку соответствия
                const assessment = analysis.match_assessment || 'Match assessment not available';
                recommendation.innerHTML = `<div class="assessment-text">${assessment}</div>`;
            }

            const improvementsList = modal.querySelector('.resume-improvements');
            if (improvementsList) {
                improvementsList.innerHTML = '';
                if (analysis.recommendations && analysis.recommendations.length > 0) {
                    analysis.recommendations.forEach(improvement => {
                        const li = document.createElement('li');
                        // Очищаем текст рекомендации от HTML-тегов и форматируем
                        const cleanText = improvement
                            .replace(/<[^>]*>/g, '')
                            .trim();
                        li.textContent = cleanText;
                        improvementsList.appendChild(li);
                    });
                } else {
                    improvementsList.innerHTML = '<li>No specific recommendations</li>';
                }
            }
        })
        .catch(error => {
            if (analysisLoader) analysisLoader.style.display = 'none';
            if (analysisContent) analysisContent.style.display = 'block';

            const recommendation = modal.querySelector('.recommendation');
            if (recommendation) {
                recommendation.textContent = 'Unable to load analysis';
            }

            const improvementsList = modal.querySelector('.resume-improvements');
            if (improvementsList) {
                improvementsList.innerHTML = '<li>Error loading recommendations. Please try again later.</li>';
            }

            console.error('Analysis error:', error);
        });
    }

    // Filter functionality
    const filterButtons = {
        apply: document.getElementById('applyFilters'),
        reset: document.getElementById('resetFilters')
    };

    const filterInputs = {
        salaryFrom: document.getElementById('salaryFrom'),
        salaryTo: document.getElementById('salaryTo'),
        salaryCurrency: document.getElementById('salaryCurrency'),
        employmentType: document.getElementById('employmentType'),
        experienceLevel: document.getElementById('experienceLevel'),
        location: document.getElementById('location')
    };

    function applyFilters() {
        const filters = {
            salaryFrom: filterInputs.salaryFrom?.value || '',
            salaryTo: filterInputs.salaryTo?.value || '',
            salaryCurrency: filterInputs.salaryCurrency?.value || '',
            employmentType: filterInputs.employmentType?.value || '',
            experienceLevel: filterInputs.experienceLevel?.value || '',
            location: filterInputs.location?.value || '',
            reset: false
        };

        if (jobCardsContainer) {
            jobCardsContainer.innerHTML = '<div class="loading-spinner">Loading...</div>';
        }

        sendFilterRequest(filters);
    }

    // Модификация функции sendFilterRequest для сохранения оригинальных значений similarity_score
function sendFilterRequest(filters) {
    fetch('/filter-vacancies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(filters)
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.error) {
            throw new Error(data.error);
        }
        
        if (data.items && Array.isArray(data.items)) {
            const formattedVacancies = data.items.map(item => {
                // Получаем исходное значение similarity_score из сохраненных originalVacancies
                let similarityScore = 0;
                if (window.originalVacancies) {
                    const originalVacancy = window.originalVacancies.find(v => v.id === item.id);
                    if (originalVacancy) {
                        similarityScore = originalVacancy.similarity_score || 0;
                    }
                }
                
                return {
                    id: item.id,
                    title: item.name,
                    company: item.employer?.name || 'Company not specified',
                    url: item.alternate_url,
                    employment_type: item.employment?.name || 'Not specified',
                    // Используем оригинальное значение или значение из ответа сервера
                    similarity_score: similarityScore || item.similarity_score || 0,
                    salary: {
                        from: item.salary?.from,
                        to: item.salary?.to,
                        currency: item.salary?.currency
                    },
                    snippet: item.snippet?.requirement || ''
                };
            });
            
            // Сортируем вакансии перед отображением
            formattedVacancies.sort((a, b) => (b.similarity_score || 0) - (a.similarity_score || 0));
            
            displayVacancies(formattedVacancies);
        } else {
            showNoVacanciesMessage();
        }
    })
    .catch(error => {
        console.error('Error applying filters:', error);
        if (jobCardsContainer) {
            jobCardsContainer.innerHTML = '<p class="error-message">Error loading vacancies. Please try again.</p>';
        }
    });
}

    // Add event listeners for filter buttons
    if (filterButtons.apply) {
        filterButtons.apply.addEventListener('click', applyFilters);
    }

    if (filterButtons.reset) {
        filterButtons.reset.addEventListener('click', () => {
            // Reset all filter inputs except location
            Object.entries(filterInputs).forEach(([key, input]) => {
                if (input && key !== 'location') {
                    if (input.tagName === 'SELECT') {
                        input.selectedIndex = 0;
                    } else {
                        input.value = '';
                    }
                }
            });
            // Apply filters after reset
            applyFilters();
        });
    }

    // Add change event listeners to all filter inputs
    Object.values(filterInputs).forEach(input => {
        if (input) {
            input.addEventListener('change', applyFilters);
        }
    });
});

