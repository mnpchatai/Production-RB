-- นำเข้าไฟล์ CSV ที่ได้จาก etl.py เข้า Supabase ด้วย psql
--
--   psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f schema.sql
--   cd data && psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f ../import.sql
--
-- รันซ้ำได้ — ล้างของเดิมก่อนเสมอ (ลำดับตาม foreign key)
-- ถ้าใช้หน้า Table Editor ของ Supabase แทน ให้ import ทีละไฟล์ตามลำดับด้านล่าง

begin;

truncate table public.rb_doc_log,
               public.rb_work_order_lines,
               public.rb_bom_lines,
               public.rb_item_standards,
               public.rb_formulas,
               public.rb_products,
               public.rb_customers,
               public.rb_colors,
               public.rb_books
  restart identity cascade;

\copy public.rb_books (code,name,source_file,app_version,doc_no,settings) from 'rb_books.csv' with (format csv, header true)
\copy public.rb_colors (book_code,seq,color_code,color_name,color_group) from 'rb_colors.csv' with (format csv, header true)
\copy public.rb_customers (book_code,seq,customer_name) from 'rb_customers.csv' with (format csv, header true)
\copy public.rb_products (book_code,seq,item_code) from 'rb_products.csv' with (format csv, header true)
\copy public.rb_formulas (book_code,seq,formula_code,batch_weight_kg,strands_per_batch,weight_per_strand_kg,min_add_weight_kg) from 'rb_formulas.csv' with (format csv, header true)
\copy public.rb_item_standards (book_code,seq,dept,rubber_type,length_txt,hole_txt,outer_txt,item_code,item_name,weight_per_strand_g,head_allowance_kg,joint_scrap_pct,general_scrap_pct,formula_code,name_variants,source_rows) from 'rb_item_standards.csv' with (format csv, header true)
\copy public.rb_bom_lines (book_code,src_row,product_item,rb_weight_g,rb_code,dept_code,formula_code,rubber_type,color_code,length_txt,hole_txt,outer_txt,rb_name,producer_dept,qty_per_set,cut_length,cut_length_unit,pcs_per_strand,pcs_unit,qty_per_gr,qty_per_gr_unit,rb_uom) from 'rb_bom_lines.csv' with (format csv, header true)
\copy public.rb_work_order_lines (book_code,src_row,seq,customer_name,production_order_no,fg_code,rb_code,rb_name,color,qty_kg,mixing_strands,rb_strands,head_allowance_kg,joint_allowance_kg,general_scrap_kg,other_dept_scrap_kg,mixing_start,injection_due,hcm_due,work_order_no,std_snapshot) from 'rb_work_order_lines.csv' with (format csv, header true)
\copy public.rb_doc_log (book_code,seq,sent_date,work_order_no,job_type,doc_count,customer_name,pi_order_no,sender,receiver) from 'rb_doc_log.csv' with (format csv, header true)

commit;

-- สรุปจำนวนแถวที่นำเข้าได้
select 'rb_books' t, count(*) from public.rb_books
union all select 'rb_colors', count(*) from public.rb_colors
union all select 'rb_customers', count(*) from public.rb_customers
union all select 'rb_products', count(*) from public.rb_products
union all select 'rb_formulas', count(*) from public.rb_formulas
union all select 'rb_item_standards', count(*) from public.rb_item_standards
union all select 'rb_bom_lines', count(*) from public.rb_bom_lines
union all select 'rb_work_order_lines', count(*) from public.rb_work_order_lines
union all select 'rb_doc_log', count(*) from public.rb_doc_log
order by 1;
