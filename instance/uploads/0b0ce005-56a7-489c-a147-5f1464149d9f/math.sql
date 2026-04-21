CREATE TABLE `classrooms` ( /*справочная таблица Аудиторий*/
  `id` int(5) NOT NULL,
  `number` varchar(4) NOT NULL /*номер аудитории*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `schedule` ( /*справочная таблица Расписания*/
  `id` int(5) NOT NULL,
  `group_id` int(5) NOT NULL, /*ссылка на таблицу Группы(groups)*/
  `subgroup_num` int(5) NOT NULL, /*номер подгруппы (1,2-у подгрупп, 0-у всей группы)*/
  `edu_semester_id` int(11) NOT NULL, /*ссылка на таблицу дисциплин по семестрам(edu_semesters)*/
  `subject_form_id` int(5) NOT NULL, /*ссылка на таблицу Формы занятий(subject_forms)*/
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `current_year` year(4) NOT NULL, /*текущий учебный год*/
  `semester` int(5) NOT NULL, /*текущий семестр*/
  `day_week` int(5) NOT NULL, /*день недели*/
  `lesson_num` int(5) NOT NULL, /*номер пары*/
  `week_num` int(5) NOT NULL, /*номер недели (1,2-черезнедельная, 0-каждую неделю)*/
  `croom_id` int(5) NOT NULL /*ссылка на таблицу Аудиторий(classrooms)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `degrees` (  /*справочная таблица по ученым степеням*/
  `id` int(5) NOT NULL,
  `title` varchar(255) NOT NULL, /*название ученой степени*/
  `short_title` varchar(10) NOT NULL  /*короткое название*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `departments` ( /*справочная таблица по кафедрам*/
  `id` int(5) NOT NULL,
  `faculty_id` int(5) NOT NULL, /*ссылка на таблицу Факультет(faculties)*/
  `title` varchar(255) NOT NULL, /*название кафедры*/
  `about` text NOT NULL, /*информация о кафедре*/
  `head_id` int(11) NOT NULL /*ссылка на таблицу Сотрудники(employees)-заведующий кафедрой*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `edu_levels` ( /*справочная таблица по уровеням образования*/
  `id` int(5) NOT NULL,
  `title` varchar(50) NOT NULL, /*название уровня*/
  `level` tinyint(1) NOT NULL DEFAULT '1' COMMENT '1-high level' /*флажок-высшее или нет*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `employees` ( /*таблица всех сотрудников*/
  `id` int(11) NOT NULL,
  `surname` varchar(30) NOT NULL, /*фамилия*/
  `name` varchar(30) NOT NULL,  /*имя*/
  `patronimyc` varchar(100) NOT NULL, /*отчество*/
  `address` text NOT NULL, /*адрес проживания*/
  `birthdate` date NOT NULL, /*дата рождения*/
  `sex` tinyint(1) NOT NULL, /*пол, 0-мужской, 1-женский*/
  `phone` varchar(11) NOT NULL,  /*телефон*/
  `email` varchar(100) NOT NULL  /*email*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_children` ( /*таблица детей всех сотрудников*/
  `id` int(11) NOT NULL,
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `surname` varchar(30) NOT NULL, /*фамилия*/
  `name` varchar(30) NOT NULL,  /*имя*/
  `patronimyc` varchar(100) NOT NULL, /*отчество*/
  `birthdate` date NOT NULL /*дата рождения*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_contracts` ( /*трудовые договора*/
  `id` int(11) NOT NULL,
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `date_from` date NOT NULL, /*дата начала действия договора*/
  `date_to` date NOT NULL, /*дата окончания действия договора*/
  `number` int(30) NOT NULL,  /*номер договора*/
  `position_id` int(11) NOT NULL, /*ссылка на таблицу Должности(positions)*/
  `competition` tinyint(1) NOT NULL COMMENT '1-election by competition' /*флажок-выбран ли по конкурсу*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_degrees` ( /*таблица присвоенных ученых степеней сотрудников*/
  `id` int(11) NOT NULL,
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `spec_id` int(11) NOT NULL, /*ссылка на таблицу Специальности-код, по которой защищался*/
  `degree_id` int(5) NOT NULL, /*ссылка на таблицу Ученые степени(degrees)*/
  `date` date NOT NULL /*дата присвоения ученой степени*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_education` ( /*таблица с базовым образованием сотрудников*/
  `id` int(11) NOT NULL,
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `edu_level_id` int(5) NOT NULL, /*ссылка на таблицу Уровни образования(edu_levels)*/
  `speciality` varchar(255) NOT NULL, /*Специальность, по которой защищался*/
  `qualification` varchar(255) NOT NULL, /*Присвоенная квалификация*/
  `date` date NOT NULL, /*дата присуждения*/
  `serial` varchar(20) NOT NULL /*серийный номер диплома*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_publications` ( /*таблица публикаций сотрудников*/
  `id` int(11) NOT NULL,
  `empl_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `publ_id` int(11) NOT NULL /*ссылка на таблицу Публикации(publications)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_titles` ( /*справочная таблица ученых званий*/
  `id` int(11) NOT NULL,
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `title_id` int(5) NOT NULL, /*ссылка на таблицу Ученые звания(titles)*/
  `date` date NOT NULL /*дата присвоения*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_awards` ( /* таблица наград преподавателей*/
  `id` int(11) NOT NULL,
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `title` varchar(255) NOT NULL, /*название награды*/
  `date` date NOT NULL /*дата присвоения*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `external_practices` ( /*таблица внешних сотрудников-практиков*/
  `id` int(11) NOT NULL,
  `empl_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `date_from` date NOT NULL, /*дата начала работы на должности*/
  `date_to` date NOT NULL, /*дата окончания работы на должности*/
  `organization` varchar(255) NOT NULL, /*наименование организации*/
  `position` varchar(255) NOT NULL, /*должность*/
  `education` tinyint(1) NOT NULL /*стаж в образоват сфере*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `faculties` ( /*справочная таблица факультетов*/
  `id` int(11) NOT NULL,
  `title` varchar(255) NOT NULL, /*наименование факультета*/
  `dean_id` int(11) NOT NULL /*ссылка на таблицу Сотрудники(employees)-декан*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `positions` ( /*справочная таблица по должностям*/
  `id` int(11) NOT NULL,
  `title` varchar(30) NOT NULL, /*название должности*/
  `level` tinyint(1) NOT NULL COMMENT '1-администрация' /*флажок-администрация факультета или нет*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `prof_doc_types` ( /*справочная таблица по виду ФПК-курсов повышения квалификации*/
  `id` int(5) NOT NULL,
  `title` varchar(255) NOT NULL /*вид квалификации*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_prof_education` ( /*таблица ФПК-курсов*/
  `id` int(11) NOT NULL,
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `number` varchar(30) NOT NULL, /*номер сертификата*/
  `date` date NOT NULL, /*дата выдачи*/
  `doc_type_id` int(5) NOT NULL, /*ссылка на таблицу Вид квалификации(prof_doc_types)*/
  `title` varchar(200) NOT NULL, /*наименование программы*/
  `n_hours` int(11) NOT NULL, /*кол-во прослушанных часов*/
  `organization` varchar(255) NOT NULL /*название организации, выдавшей сертификат*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `publications` ( /*таблица публикаций*/
  `id` int(11) NOT NULL,
  `title` varchar(255) NOT NULL, /*название публикации*/
  `DOI` varchar(50) NOT NULL, /*DOI адрес*/
  `imprint` text NOT NULL, /*выходные данные статьи*/
  `publ_level_id` int(5) NOT NULL, /*ссылка на таблицу Уровень публикации(publ_levels)*/
  `type` varchar(1) DEFAULT 'A' COMMENT 'A-article, P-posobie' /*флажок-вид публикации*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `publ_levels` ( /*справочная таблица по уровням публикации*/
  `id` int(5) NOT NULL,
  `title` varchar(50) NOT NULL /*наименование*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `speciality` ( /*справочная таблица специальностей*/
  `id` int(11) NOT NULL,
  `title` varchar(150) NOT NULL, /*название специальности*/
  `code` varchar(30) NOT NULL, /*код вида 00.00.00*/
  `profile` varchar(255) NOT NULL, /*профиль для бакалавриата/магистратуры*/
  `edu_level_id` int(5) NOT NULL /*ссылка на таблицу Уровни обучения(edu_levels)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `titles` ( /*справочная таблица ученых званий*/
  `id` int(5) NOT NULL,
  `title` varchar(50) NOT NULL /*наименование*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `edu_forms` ( /*справочная таблица Форм обучения*/
  `id` int(5) NOT NULL,
  `title` varchar(20) NOT NULL /*Название (очная,заочная и тд)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `block` ( /*справочная таблица Блоки учебного плана*/
  `id` int(5) NOT NULL,
  `block_title` varchar(255) NOT NULL, /*Название блока (Блок 1.Дисциплины (модули) и тд)*/
  `part_title` varchar(255) NOT NULL /*Название части блока (Обязательная, Вариативная и тд)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `competence` ( /*справочная таблица Компетенций*/
  `id` int(5) NOT NULL,
  `code` varchar(6) NOT NULL, /*код компетенции*/
  `description` text NOT NULL, /*описание*/
  `speciality_id` int(11) NOT NULL /*ссылка на таблицу Специальности (speciality)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `edu_plan` ( /*таблица Учебный план (страница с дисциплинами)*/
  `id` int(11) NOT NULL,
  `block_id` int(5) NOT NULL, /*ссылка на таблицу Блоки учебного плана*/
  `subject_id` int(11) NOT NULL, /*ссылка на таблицу Дисциплины*/
  `code_subject` varchar(10) NOT NULL, /*код дисциплины в данном учебном плане*/
  `department_id` int(5) NOT NULL, /*кафедра, за которой закреплена дисциплина*/
  `title_plan_id` int(11) NOT NULL /*ссылка на таблицу Титульного листа учебного плана (title_plan)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `edu_plan_competencies` ( /*Таблица связи дисциплин из плана со списком компетенций*/
  `id` int(5) NOT NULL,
  `edu_plan_id` int(11) NOT NULL, /*ссылка на таблицу Учебный план(edu_plan)*/
  `competency_id` int(5) NOT NULL /*ссылка на таблицу Компетенций(competence)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `form_control` ( /*справочная таблица форм контроля*/
  `id` int(5) NOT NULL,
  `title` varchar(50) NOT NULL /*название (зачет,экзамен,дифф.зачет)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `edu_plan_form_control` ( /*Таблица связи дисциплин из плана (edu_semesters) и форм контроля(form_control)*/
  `id` int(11) NOT NULL,
  `edu_semester_id` int(11) NOT NULL, /*ссылка на таблицу Учебный план(edu_semesters)*/
  `form_control_id` int(5) NOT NULL /*ссылка на таблицу Форм контроля(form_control)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `groups` ( /*Таблица групп студенческих*/
  `id` int(5) NOT NULL,
  `title` varchar(30) NOT NULL, /*название группы (ПМ(б)-20-1-ОФО)*/
  `galactika_number` int(5) NOT NULL, /*номер в Galaktika (6153)*/
  `year` year(4) NOT NULL, /*год поступления*/
  `speciality_id` int(11) NOT NULL /*ссылка на таблицу специальности (speciality)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `loads` ( /*таблица нагрузок-титул*/
  `id` int(11) NOT NULL,
  `current_year` year(4) NOT NULL, /*текущий учебный год*/
  `department_id` int(5) NOT NULL /*ссылка на таблицу Кафедры(departments)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `subject_forms` ( /*справочная таблица форм занятий*/
  `id` int(11) NOT NULL,
  `title` varchar(255) NOT NULL /*название (лекция,...)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_loads` ( /*таблица нагрузок преподавателей*/
  `id` int(11) NOT NULL,
  `load_id` int(11) NOT NULL, /*ссылка на таблицу титулов нагрузок(loads)*/
  `semester` int(5) NOT NULL, /*номер семестра*/
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)*/
  `hourly_fund` tinyint(1) NOT NULL DEFAULT '0', /*почасовка-1, остальные-0*/
  `edu_semester_id` int(11) NOT NULL, /*для внутренних предметов ссылка на таблицу дисциплин по семестрам(edu_semesters)*/
  `subject` varchar(255) NOT NULL, /*для межфаковских предметов название дисциплины*/
  `group_id` int(5) NOT NULL, /*ссылка на таблицу Группы(groups)*/
  `subject_form_id` int(5) NOT NULL, /*ссылка на таблицу Формы занятий(subject_forms)*/
  `hours_other` decimal(10,2) NOT NULL, /*часы неаудиторной нагрузки*/
  `hours_contact` decimal(10,2) NOT NULL /*часы аудиторной нагрузки*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `empl_loads_streams` ( /*таблица связи потоковых пар*/
  `id` int(5) NOT NULL,
  `empl_loads_id1` int(11) NOT NULL, /*ссылка на таблицу нагрузок преподов (empl_loads)*/
  `empl_loads_id2` int(11) NOT NULL /*ссылка на таблицу нагрузок преподов (empl_loads)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `order_types` ( /*справочная таблица типов приказов*/
  `id` int(5) NOT NULL,
  `type` varchar(30) NOT NULL /*тип приказа (зачисление,перевод,отчисление)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `orders` ( /*таблица приказов*/
  `id` int(11) NOT NULL,
  `date` date NOT NULL, /*дата приказа*/
  `number` varchar(30) NOT NULL, /*номер приказа*/
  `title` varchar(255) NOT NULL, /*название приказа*/
  `order_type_id` int(5) NOT NULL /*ссылка на таблицу типов приказов (order_types)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `students` ( /*таблица Студентов*/
  `id` int(11) NOT NULL,
  `surname` varchar(50) NOT NULL, /*фамилия*/
  `name` varchar(50) NOT NULL, /*имя*/
  `patronymic` varchar(50) NOT NULL, /*отчество*/
  `birth_year` year(4) NOT NULL, /*год рождения*/
  `speciality_id` varchar(100) NOT NULL, /*ссылка на таблицу Специальности(speciality)*/
  `date_enter` year(4) NOT NULL, /*год поступления*/
  `group_id` int(5) NOT NULL /*ссылка на таблицу Группы(groups)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `stud_orders` ( /*Таблица связи между студентами(students) и приказами (orders)*/
  `id` int(11) NOT NULL,
  `student_id` int(11) NOT NULL, /*ссылка на таблицу студентов*/
  `order_id` int(11) NOT NULL /*ссылка на таблицу приказов*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `subjects` ( /*таблица Дисциплин*/
  `id` int(11) NOT NULL,
  `title` varchar(50) NOT NULL /*наименование дисциплины*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `title_plan` ( /*Таблица с титульными листами учебных планов*/
  `id` int(11) NOT NULL,
  `spec_id` int(11) NOT NULL, /*ссылка на таблицу Специальности(speciality)-код, по которой защищался*/
  `date_uchsovet` date NOT NULL, /*дата протокола ученого совета*/
  `number_uchsovet` int(5) NOT NULL, /*номер протокола ученого совета*/
  `current_year` year(4) NOT NULL, /*текущий год обучения*/
  `date_enter` year(4) NOT NULL, /*год поступления учащихся по данному плану*/
  `date_fgos` date NOT NULL, /*дата протокола ФГОС*/
  `number_fgos` int(5) NOT NULL, /*номер протокола ФГОС*/
  `department_id` int(5) NOT NULL, /*ссылка на таблицу Кафедры(departments), отвечающей за направление*/
  `included` varchar(1) NOT NULL /*активный-1,черновик-0*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `edu_semesters` ( /*Таблица с дисциплинами по семестрам*/
  `id` int(11) NOT NULL,
  `edu_plan_id` int(11) NOT NULL, /*ссылка на таблицу Учебный план(edu_plan)-дисциплина*/
  `semester` int(5) NOT NULL, /*номер семестра*/
  `zed` decimal(10,2) NOT NULL, /*количество зет*/
  `lecture` int(11) NOT NULL, /*часы лекций*/
  `practice` int(11) NOT NULL, /*часы практик*/
  `laboratory` int(11) NOT NULL, /*часы лабораторных*/
  `ind_work` int(11) NOT NULL /*часы самостоятельной работы*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `thesis_work_type` ( /*таблица видов студ работ*/
  `id` int(5) NOT NULL,
  `title` varchar(255) NOT NULL /*название работы (курсовая,дипломная,маг дисс)*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

CREATE TABLE `thesis_work` ( /*Таблица студенческих работ*/
  `id` int(11) NOT NULL,
  `current_year` year(4) NOT NULL, /*учебный год*/
  `semester` int(5) NOT NULL, /*номер семестра*/
  `student_id` int(11) NOT NULL, /*ссылка на таблицу Студенты(students)*/
  `employee_id` int(11) NOT NULL, /*ссылка на таблицу Сотрудники(employees)-науч рук*/
  `title` varchar(255) NOT NULL, /*название работы*/
  `thesis_work_type_id` int(5) NOT NULL, /*ссылка на таблицу Виды студ работ(thesis_work_type)*/
  `mark` int(5) NOT NULL /*оценка*/
) ENGINE=InnoDB DEFAULT CHARSET=cp1251;

--
-- Индексы сохранённых таблиц
--

--
-- Индексы таблицы `block`
--
ALTER TABLE `block`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `competence`
--
ALTER TABLE `competence`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `edu_forms`
--
ALTER TABLE `edu_forms`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `edu_plan`
--
ALTER TABLE `edu_plan`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `edu_plan_competencies`
--
ALTER TABLE `edu_plan_competencies`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `edu_plan_form_control`
--
ALTER TABLE `edu_plan_form_control`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `edu_semesters`
--
ALTER TABLE `edu_semesters`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `empl_loads`
--
ALTER TABLE `empl_loads`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `form_control`
--
ALTER TABLE `form_control`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `groups`
--
ALTER TABLE `groups`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `loads`
--
ALTER TABLE `loads`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `orders`
--
ALTER TABLE `orders`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `order_types`
--
ALTER TABLE `order_types`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `students`
--
ALTER TABLE `students`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `stud_orders`
--
ALTER TABLE `stud_orders`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `subjects`
--
ALTER TABLE `subjects`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `subject_forms`
--
ALTER TABLE `subject_forms`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `thesis_work`
--
ALTER TABLE `thesis_work`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `thesis_work_type`
--
ALTER TABLE `thesis_work_type`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `title_plan`
--
ALTER TABLE `title_plan`
  ADD PRIMARY KEY (`id`);


--
-- Индексы таблицы `degrees`
--
ALTER TABLE `degrees`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `departments`
--
ALTER TABLE `departments`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `edu_levels`
--
ALTER TABLE `edu_levels`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `employees`
--
ALTER TABLE `employees`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `empl_contracts`
--
ALTER TABLE `empl_contracts`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `empl_degrees`
--
ALTER TABLE `empl_degrees`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `empl_education`
--
ALTER TABLE `empl_education`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `empl_prof_education`
--
ALTER TABLE `empl_prof_education`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `empl_publications`
--
ALTER TABLE `empl_publications`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `empl_titles`
--
ALTER TABLE `empl_titles`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `external_practices`
--
ALTER TABLE `external_practices`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `faculties`
--
ALTER TABLE `faculties`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `positions`
--
ALTER TABLE `positions`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `prof_doc_types`
--
ALTER TABLE `prof_doc_types`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `publications`
--
ALTER TABLE `publications`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `publ_levels`
--
ALTER TABLE `publ_levels`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `speciality`
--
ALTER TABLE `speciality`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `titles`
--
ALTER TABLE `titles`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `schedule`
--
ALTER TABLE `schedule`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `classrooms`
--
ALTER TABLE `classrooms`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `empl_awards`
--
ALTER TABLE `empl_awards`
  ADD PRIMARY KEY (`id`);

--
-- Индексы таблицы `empl_loads_streams`
--
ALTER TABLE `empl_loads_streams`
  ADD PRIMARY KEY (`id`);


--
-- AUTO_INCREMENT для сохранённых таблиц
--

--
-- AUTO_INCREMENT для таблицы `block`
--
ALTER TABLE `block`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `competence`
--
ALTER TABLE `competence`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `edu_forms`
--
ALTER TABLE `edu_forms`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `edu_plan`
--
ALTER TABLE `edu_plan`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `edu_plan_competencies`
--
ALTER TABLE `edu_plan_competencies`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `edu_plan_form_control`
--
ALTER TABLE `edu_plan_form_control`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `edu_semesters`
--
ALTER TABLE `edu_semesters`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `empl_loads`
--
ALTER TABLE `empl_loads`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `form_control`
--
ALTER TABLE `form_control`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `groups`
--
ALTER TABLE `groups`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `loads`
--
ALTER TABLE `loads`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `orders`
--
ALTER TABLE `orders`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `order_types`
--
ALTER TABLE `order_types`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `students`
--
ALTER TABLE `students`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `stud_orders`
--
ALTER TABLE `stud_orders`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `subjects`
--
ALTER TABLE `subjects`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `subject_forms`
--
ALTER TABLE `subject_forms`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `thesis_work`
--
ALTER TABLE `thesis_work`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `thesis_work_type`
--
ALTER TABLE `thesis_work_type`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `title_plan`
--
ALTER TABLE `title_plan`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;
COMMIT;


--
-- AUTO_INCREMENT для таблицы `degrees`
--
ALTER TABLE `degrees`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT для таблицы `departments`
--
ALTER TABLE `departments`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT для таблицы `edu_levels`
--
ALTER TABLE `edu_levels`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6;

--
-- AUTO_INCREMENT для таблицы `employees`
--
ALTER TABLE `employees`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT для таблицы `empl_contracts`
--
ALTER TABLE `empl_contracts`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `empl_degrees`
--
ALTER TABLE `empl_degrees`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `empl_education`
--
ALTER TABLE `empl_education`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `empl_prof_education`
--
ALTER TABLE `empl_prof_education`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `empl_publications`
--
ALTER TABLE `empl_publications`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `empl_titles`
--
ALTER TABLE `empl_titles`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `external_practices`
--
ALTER TABLE `external_practices`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `faculties`
--
ALTER TABLE `faculties`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT для таблицы `positions`
--
ALTER TABLE `positions`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=8;

--
-- AUTO_INCREMENT для таблицы `prof_doc_types`
--
ALTER TABLE `prof_doc_types`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT для таблицы `publications`
--
ALTER TABLE `publications`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `publ_levels`
--
ALTER TABLE `publ_levels`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6;

--
-- AUTO_INCREMENT для таблицы `speciality`
--
ALTER TABLE `speciality`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT для таблицы `titles`
--
ALTER TABLE `titles`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;
COMMIT;

--
-- AUTO_INCREMENT для сохранённых таблиц
--

--
-- AUTO_INCREMENT для таблицы `schedule`
--
ALTER TABLE `schedule`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `classrooms`
--
ALTER TABLE `classrooms`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;


--
-- AUTO_INCREMENT для таблицы `empl_awards`
--
ALTER TABLE `empl_awards`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `empl_loads_streams`
--
ALTER TABLE `empl_loads_streams`
  MODIFY `id` int(5) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT для таблицы `empl_children`
--
ALTER TABLE `empl_children` CHANGE `id` `id` INT(11) NOT NULL AUTO_INCREMENT, add PRIMARY KEY (`id`);